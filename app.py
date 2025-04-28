# -*- coding: utf-8 -*-
# stereotype_quiz_app/app_cross_state.py (Refactored Version with Mandatory Age)

import os
import csv
import io
import random
import mysql.connector
from mysql.connector import Error as MySQLError
from flask import (Flask, render_template, request, redirect, url_for, g,
                   flash, Response, send_file, session, current_app) # Added current_app
import pandas as pd
import numpy as np
from dotenv import load_dotenv
import logging
import sys
import traceback

# --- Load Environment Variables ---
load_dotenv() # For local development via .env file

# --- Configuration ---
CSV_FILE_PATH = os.path.join('data', 'stereotypes.csv')
# Schema file should define BOTH results_cross AND familiarity_ratings tables
SCHEMA_FILE = 'schema.sql' # Ensure this file exists and is correct

# --- Load Config from Environment Variables ---
SECRET_KEY = os.environ.get('SECRET_KEY')
MYSQL_HOST = os.environ.get('MYSQL_HOST')
MYSQL_USER = os.environ.get('MYSQL_USER')
MYSQL_PASSWORD = os.environ.get('MYSQL_PASSWORD')
MYSQL_DB = os.environ.get('MYSQL_DB') # Should be 'stereotype_cross' in env vars
MYSQL_PORT = int(os.environ.get('MYSQL_PORT', 3306))

# Define table names used in this version
RESULTS_TABLE_CROSS = 'results_cross'
FAMILIARITY_TABLE = 'familiarity_ratings'

# --- Flask App Initialization ---
app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
app.config['MYSQL_HOST'] = MYSQL_HOST
app.config['MYSQL_USER'] = MYSQL_USER
app.config['MYSQL_PASSWORD'] = MYSQL_PASSWORD
app.config['MYSQL_DB'] = MYSQL_DB
app.config['MYSQL_PORT'] = MYSQL_PORT

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]')
app.logger.setLevel(logging.INFO)

app.logger.info("Flask application (Cross-State Version) starting...")

# --- Configuration Validation ---
if not SECRET_KEY:
    app.logger.critical("CRITICAL ERROR: SECRET_KEY not set. Flask sessions WILL NOT WORK.")
if not all([MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DB]):
    app.logger.critical("CRITICAL ERROR: Database configuration missing in environment variables.")
else:
    app.logger.info(f"Database config loaded: Host={MYSQL_HOST}, User={MYSQL_USER}, DB={MYSQL_DB}, Port={MYSQL_PORT}")

# --- Database Functions ---
def get_db():
    if 'db' not in g:
        try:
            g.db = mysql.connector.connect(
                host=current_app.config['MYSQL_HOST'],
                user=current_app.config['MYSQL_USER'],
                password=current_app.config['MYSQL_PASSWORD'],
                database=current_app.config['MYSQL_DB'],
                port=current_app.config['MYSQL_PORT'],
                autocommit=False,
                connection_timeout=10
            )
            g.cursor = g.db.cursor(dictionary=True)
            app.logger.debug("Request DB connection established.")
        except MySQLError as err:
            app.logger.error(f"Error connecting to MySQL: {err}", exc_info=True)
            flash('Database connection error. Please contact admin.', 'error')
            g.db = None; g.cursor = None
    return getattr(g, 'cursor', None)

@app.teardown_appcontext
def close_db(error):
    cursor = g.pop('cursor', None)
    if cursor:
        try: cursor.close()
        except Exception as e: app.logger.warning(f"Error closing cursor: {e}")
    db = g.pop('db', None)
    if db and db.is_connected():
        try: db.close(); app.logger.debug("Request DB connection closed.")
        except Exception as e: app.logger.warning(f"Error closing DB connection: {e}")
    if error: app.logger.error(f"App context teardown error: {error}", exc_info=True)

def init_db():
    """Initializes the database schema if tables are missing."""
    db_host = current_app.config['MYSQL_HOST']; db_user = current_app.config['MYSQL_USER']
    db_password = current_app.config['MYSQL_PASSWORD']; db_name = current_app.config['MYSQL_DB']
    db_port = current_app.config['MYSQL_PORT']
    if not all([db_host, db_user, db_password, db_name]):
        app.logger.error("Cannot initialize DB: Environment configuration missing.")
        return False
    temp_conn = None; temp_cursor = None
    app.logger.info(f"Checking database '{db_name}' setup...")
    tables_exist = {RESULTS_TABLE_CROSS: False, FAMILIARITY_TABLE: False}
    schema_executed = False
    try:
        temp_conn = mysql.connector.connect(host=db_host, user=db_user, password=db_password, database=db_name, port=db_port)
        temp_cursor = temp_conn.cursor()
        for table_name in tables_exist:
            temp_cursor.execute(f"SHOW TABLES LIKE '{table_name}'")
            if temp_cursor.fetchone():
                tables_exist[table_name] = True
                app.logger.info(f"Table '{table_name}' already exists.")
        if not all(tables_exist.values()):
            app.logger.warning(f"One or more required tables missing. Attempting creation using '{SCHEMA_FILE}'...")
            schema_path = os.path.join(current_app.root_path, SCHEMA_FILE)
            if not os.path.exists(schema_path):
                 app.logger.error(f"FATAL: Schema file '{SCHEMA_FILE}' not found at: {schema_path}")
                 return False
            try:
                with open(schema_path, mode='r', encoding='utf-8') as f: sql_script = f.read()
                app.logger.info(f"Executing SQL script from {schema_path}...")
                for result in temp_cursor.execute(sql_script, multi=True):
                    app.logger.debug(f"Schema exec result: Stmt='{result.statement[:50]}...', Rows={result.rowcount}")
                    if result.with_rows: result.fetchall()
                temp_conn.commit()
                schema_executed = True
                app.logger.info(f"Database tables from '{SCHEMA_FILE}' created/verified successfully.")
            except MySQLError as err:
                app.logger.error(f"Error executing schema file '{SCHEMA_FILE}': {err}", exc_info=True)
                temp_conn.rollback()
            except Exception as e:
                app.logger.error(f"Unexpected error initializing schema from file: {e}", exc_info=True)
                temp_conn.rollback()
        else:
            app.logger.info("All required database tables already exist.")
    except MySQLError as err:
        app.logger.error(f"Error during DB connection or table check for initialization: {err}", exc_info=True)
    except Exception as e:
        app.logger.error(f"Unexpected error during DB initialization: {e}", exc_info=True)
    finally:
        if temp_cursor: temp_cursor.close()
        if temp_conn and temp_conn.is_connected(): temp_conn.close()
        app.logger.debug("DB init connection closed.")
    return all(tables_exist.values()) or schema_executed

# --- Data Loading Function ---
def load_stereotype_data(relative_filepath=CSV_FILE_PATH):
    stereotype_data = []
    base_path = current_app.root_path if current_app else os.path.dirname(os.path.abspath(__file__))
    full_filepath = os.path.join(base_path, relative_filepath)
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    logger.info(f"Attempting to load stereotype data from: {full_filepath}")
    try:
        if not os.path.exists(full_filepath): raise FileNotFoundError(f"{full_filepath}")
        with open(full_filepath, mode='r', encoding='utf-8-sig') as infile:
            reader = csv.DictReader(infile)
            required_cols = ['State', 'Category', 'Superset', 'Subsets']
            if not reader.fieldnames or not all(field in reader.fieldnames for field in required_cols):
                 missing = [c for c in required_cols if c not in (reader.fieldnames or [])]
                 raise ValueError(f"CSV missing required columns: {missing}. Found: {reader.fieldnames}")
            for i, row in enumerate(reader):
                try:
                    state = row.get('State','').strip(); category = row.get('Category','Uncategorized').strip()
                    superset = row.get('Superset','').strip(); subsets_str = row.get('Subsets','')
                    if not state or not superset: continue
                    subsets = sorted([s.strip() for s in subsets_str.split(',') if s.strip()])
                    stereotype_data.append({'state': state, 'category': category, 'superset': superset, 'subsets': subsets})
                except Exception as row_err: logger.warning(f"Error processing CSV row {i+1}: {row_err}")
        logger.info(f"Loaded {len(stereotype_data)} stereotype entries.")
        return stereotype_data
    except FileNotFoundError as e: logger.critical(f"FATAL: Stereotype CSV not found: {e}"); return []
    except ValueError as ve: logger.critical(f"FATAL: Error processing stereotype CSV: {ve}"); return []
    except Exception as e: logger.critical(f"FATAL: Unexpected error loading stereotype data: {e}", exc_info=True); return []

# --- Load Data & Get List of States ---
with app.app_context():
    ALL_STEREOTYPE_DATA = load_stereotype_data()
    if ALL_STEREOTYPE_DATA:
        ALL_DEFINED_STATES = sorted(list(set(item['state'] for item in ALL_STEREOTYPE_DATA)))
        app.logger.info(f"States loaded ({len(ALL_DEFINED_STATES)} unique).")
    else:
        app.logger.error("CRITICAL: Stereotype data loading failed! App cannot function.")
        ALL_DEFINED_STATES = ["Error: State Data Load Failed"]

# --- Data Processing Logic ---
def calculate_mean_offensiveness(series):
    valid_ratings = series[series >= 0]
    return valid_ratings.mean() if not valid_ratings.empty else np.nan

# --- REFACTORED generate_aggregated_data (No longer used in this app version) ---
# This function processed the *single-state* results. This app saves to different tables.
# You might create different processing functions for the cross-state data later if needed.

# --- Flask Routes ---

@app.route('/', methods=['GET', 'POST'])
def index():
    """Handles the initial user info form page for cross-state annotation."""
    if request.method == 'POST':
        user_name = request.form.get('name', '').strip()
        native_state = request.form.get('native_state')
        user_age_str = request.form.get('age') # Get the age string
        user_sex = request.form.get('sex')

        errors = False
        if not user_name: flash('Name is required.', 'error'); errors = True
        # Check if states loaded before validating native_state
        if "Error: State Data Load Failed" in ALL_DEFINED_STATES:
            flash('Application Error: Cannot load state data. Please contact support.', 'error')
            # Render template immediately if states failed to load, prevents further errors
            return render_template('index.html', states=ALL_DEFINED_STATES, form_data=request.form, error_state=True)
        elif not native_state or native_state not in ALL_DEFINED_STATES:
            flash('Please select your valid native state.', 'error'); errors = True
        if not user_sex: flash('Please select your sex.', 'error'); errors = True

        user_age = None
        # --- MANDATORY AGE VALIDATION ---
        if not user_age_str: # Check if age string is empty
             flash('Age is required.', 'error')
             errors = True
        elif user_age_str: # Only try conversion if it's not empty
            try:
                user_age = int(user_age_str)
                if user_age < 1: # Optional: Add minimum age check
                     flash('Please enter a valid age.', 'error'); errors = True
            except ValueError:
                flash('Please enter a valid number for age.', 'error')
                errors = True
        # --- END MANDATORY AGE VALIDATION ---

        if errors:
            # Pass states list even on error
            return render_template('index.html', states=ALL_DEFINED_STATES, form_data=request.form)

        # Setup Session for the Quiz
        session.clear()
        session['user_name'] = user_name
        session['native_state'] = native_state
        session['user_age'] = user_age # Stored as int or None
        session['user_sex'] = user_sex

        target_states = [s for s in ALL_DEFINED_STATES if s != native_state]
        if not target_states:
            app.logger.info(f"User '{user_name}' has no target states to annotate (native state: {native_state}).")
            flash("No other states found to annotate. Thank you!", 'info')
            return redirect(url_for('thank_you'))

        random.shuffle(target_states)
        session['target_states'] = target_states
        session['current_state_index'] = 0
        session.modified = True

        app.logger.info(f"User '{user_name}' (Native: {native_state}) starting. Targets: {len(target_states)} states.")
        return redirect(url_for('quiz_cross'))

    # GET request
    session.clear()
    if "Error: State Data Load Failed" in ALL_DEFINED_STATES:
        flash("Application Error: Could not load state data.", "error")
        return render_template('index.html', states=ALL_DEFINED_STATES, form_data={}, error_state=True)
    return render_template('index.html', states=ALL_DEFINED_STATES, form_data={})


@app.route('/quiz', methods=['GET', 'POST'])
def quiz_cross():
    """Handles the sequential display and submission for each target state."""
    required_session_keys = ['user_name', 'native_state', 'target_states', 'current_state_index']
    if not all(key in session for key in required_session_keys):
        app.logger.warning("Invalid session state detected in /quiz route. Redirecting to index.")
        flash('Your session has expired or is invalid. Please start again.', 'warning')
        return redirect(url_for('index'))

    target_states = session['target_states']
    current_index = session['current_state_index']

    if current_index >= len(target_states):
        app.logger.info(f"User '{session['user_name']}' finished all states ({len(target_states)}).")
        return redirect(url_for('thank_you'))

    current_target_state = target_states[current_index]
    app.logger.debug(f"Processing state index {current_index}: {current_target_state}")

    if request.method == 'POST':
        app.logger.info(f"POST received for state index {current_index} ({current_target_state})")
        cursor = get_db()
        if not cursor:
            app.logger.error("Quiz POST failed: Could not get DB cursor.")
            return redirect(url_for('index'))
        db_connection = g.db

        try:
            familiarity_rating_str = request.form.get('familiarity_rating')
            if familiarity_rating_str is None:
                 app.logger.error("Submission error: Familiarity rating missing from form POST.")
                 flash('Error: Familiarity rating was not submitted. Please try again.', 'error')
                 return redirect(url_for('quiz_cross'))

            try:
                familiarity_rating = int(familiarity_rating_str)
                if not (0 <= familiarity_rating <= 5): raise ValueError("Rating out of range")
            except (ValueError, TypeError):
                app.logger.error(f"Invalid familiarity rating '{familiarity_rating_str}' submitted.")
                flash('Invalid familiarity rating. Please select a value between 0 and 5.', 'error')
                return redirect(url_for('quiz_cross'))

            app.logger.info(f"Saving familiarity rating ({familiarity_rating}) for state {current_target_state}...")
            fam_sql = f"""INSERT INTO {FAMILIARITY_TABLE}
                          (native_state, target_state, familiarity_rating, user_name, user_age, user_sex)
                          VALUES (%(native_state)s, %(target_state)s, %(rating)s, %(name)s, %(age)s, %(sex)s)"""
            fam_data = {'native_state': session['native_state'], 'target_state': current_target_state,
                        'rating': familiarity_rating, 'name': session['user_name'],
                        'age': session.get('user_age'), 'sex': session.get('user_sex')}
            cursor.execute(fam_sql, fam_data)
            app.logger.info("Familiarity rating insertion successful (pre-commit).")

            annotations_to_insert = []
            num_items_on_page = int(request.form.get('num_quiz_items', 0))
            app.logger.debug(f"Parsing annotations for {num_items_on_page} items on page.")

            for i in range(num_items_on_page):
                identifier = str(i)
                superset = request.form.get(f'superset_{identifier}')
                category = request.form.get(f'category_{identifier}')
                annotation = request.form.get(f'annotation_{identifier}')
                if not annotation or not superset or not category:
                    app.logger.warning(f"Skipping item index {identifier} on state {current_target_state}: missing annotation/data.")
                    continue
                offensiveness = -1
                if annotation == 'Stereotype':
                    rating_str = request.form.get(f'offensiveness_{identifier}')
                    if rating_str is not None and rating_str.isdigit():
                        rating_val = int(rating_str)
                        if 0 <= rating_val <= 5: offensiveness = rating_val
                        else: app.logger.warning(f"Annotation item {identifier}: Out-of-range rating ({rating_val}). Defaulting to -1.")
                    elif rating_str is not None: app.logger.warning(f"Annotation item {identifier}: Non-integer rating ('{rating_str}'). Defaulting to -1.")
                annotations_to_insert.append({
                    'native_state': session['native_state'], 'target_state': current_target_state,
                    'user_name': session['user_name'], 'user_age': session.get('user_age'),
                    'user_sex': session.get('user_sex'), 'category': category,
                    'attribute_superset': superset, 'annotation': annotation,
                    'offensiveness_rating': offensiveness
                })

            if annotations_to_insert:
                app.logger.info(f"Inserting {len(annotations_to_insert)} annotations for state {current_target_state}...")
                results_sql = f"""INSERT INTO {RESULTS_TABLE_CROSS}
                                  (native_state, target_state, user_name, user_age, user_sex, category, attribute_superset, annotation, offensiveness_rating)
                                  VALUES (%(native_state)s, %(target_state)s, %(user_name)s, %(user_age)s, %(user_sex)s, %(category)s, %(attribute_superset)s, %(annotation)s, %(offensiveness_rating)s)"""
                cursor.executemany(results_sql, annotations_to_insert)
                rowcount = cursor.rowcount
                app.logger.info(f"Annotation insertion successful (rowcount={rowcount}, pre-commit).")
            else:
                app.logger.warning(f"No valid annotations parsed for state {current_target_state}. Only familiarity rating will be saved.")

            app.logger.info(f"Committing transaction for state {current_target_state}...")
            db_connection.commit()
            app.logger.info(f"COMMIT successful for state {current_target_state}.")

            session['current_state_index'] = current_index + 1
            session.modified = True
            app.logger.info(f"Advancing to state index {session['current_state_index']}.")
            return redirect(url_for('quiz_cross'))

        except MySQLError as db_err:
            app.logger.error(f"DB Error saving data for state {current_target_state}: {db_err}", exc_info=True)
            try: db_connection.rollback(); app.logger.info("Rolled back transaction due to DB error.")
            except Exception as rb_err: app.logger.error(f"Rollback failed after DB error: {rb_err}")
            flash("Database error saving responses. Please try submitting this state again.", 'error')
            return redirect(url_for('quiz_cross'))

        except Exception as e:
            app.logger.error(f"Unexpected error processing POST for state {current_target_state}: {e}", exc_info=True)
            try: db_connection.rollback(); app.logger.info("Rolled back transaction due to unexpected error.")
            except Exception as rb_err: app.logger.error(f"Rollback failed after unexpected error: {rb_err}")
            flash("An unexpected server error occurred. Please start again.", 'error')
            return redirect(url_for('index'))

    # Handle GET Request
    app.logger.info(f"GET request for state index {current_index} ({current_target_state})")
    # Check if states data is available before filtering
    if "Error: State Data Load Failed" in ALL_DEFINED_STATES:
         app.logger.error("Cannot display quiz page because state data failed to load.")
         flash("Application error: Cannot load stereotype data.", "error")
         return redirect(url_for('index'))

    quiz_items_for_state = [item for item in ALL_STEREOTYPE_DATA if item['state'] == current_target_state]
    is_last_state = (current_index == len(target_states) - 1)
    app.logger.debug(f"Rendering quiz for {current_target_state}. Items: {len(quiz_items_for_state)}. Last State: {is_last_state}")

    return render_template('quiz.html',
                           target_state=current_target_state,
                           quiz_items=quiz_items_for_state,
                           user_info=session,
                           current_index=current_index,
                           total_states=len(target_states),
                           is_last_state=is_last_state,
                           num_quiz_items=len(quiz_items_for_state))


@app.route('/thank_you')
def thank_you():
    """Displays the thank you page."""
    user_name = session.get('user_name', 'Participant')
    app.logger.info(f"Displaying thank you page for user '{user_name}'.")
    return render_template('thank_you.html', user_name=user_name)


# --- Admin Routes ---
# !! SECURITY WARNING: Add authentication !!
@app.route('/admin')
def admin_view():
    """Displays raw annotation results and familiarity ratings."""
    app.logger.info("Admin route entered.")
    app.logger.warning("Accessed unsecured /admin route.")
    cursor = get_db()
    if not cursor: app.logger.error("Admin view failed: No DB cursor."); return redirect(url_for('index'))

    results_data = []; familiarity_data = []
    try:
        app.logger.info(f"Admin view: Fetching data from {RESULTS_TABLE_CROSS}...")
        cursor.execute(f"SELECT * FROM {RESULTS_TABLE_CROSS} ORDER BY timestamp DESC")
        results_data = cursor.fetchall()
        app.logger.info(f"Admin view: Fetched {len(results_data)} annotations.")

        app.logger.info(f"Admin view: Fetching data from {FAMILIARITY_TABLE}...")
        cursor.execute(f"SELECT * FROM {FAMILIARITY_TABLE} ORDER BY timestamp DESC")
        familiarity_data = cursor.fetchall()
        app.logger.info(f"Admin view: Fetched {len(familiarity_data)} familiarity ratings.")

    except MySQLError as err:
        app.logger.error(f"Admin view: Error fetching data: {err}", exc_info=True); flash('Error fetching results.', 'error')
    except Exception as e:
        app.logger.error(f"Admin view: Unexpected error fetching data: {e}", exc_info=True); flash('Unexpected error.', 'error')

    app.logger.debug("Admin view: Rendering template.")
    return render_template('admin.html', results=results_data, familiarity_ratings=familiarity_data)

# --- REFACTORED Download Routes (using direct connection) ---
def fetch_data_as_df(table_name):
    """Helper function to fetch all data from a table into a DataFrame using direct connection."""
    app.logger.info(f"Helper: Attempting to fetch data from '{table_name}'")
    db_conn = None; cursor = None; data_list = []
    try:
        db_host = current_app.config['MYSQL_HOST']; db_user = current_app.config['MYSQL_USER']
        db_password = current_app.config['MYSQL_PASSWORD']; db_name = current_app.config['MYSQL_DB']
        db_port = current_app.config['MYSQL_PORT']
        if not all([db_host, db_user, db_password, db_name]):
            app.logger.error(f"Helper fetch_data_as_df: DB config missing for {table_name}.")
            return None
        app.logger.debug(f"Helper fetch_data_as_df: Connecting directly to DB for {table_name}...")
        db_conn = mysql.connector.connect(host=db_host, user=db_user, password=db_password, database=db_name, port=db_port, connection_timeout=10)
        cursor = db_conn.cursor(dictionary=True)
        cursor.execute(f"SELECT * FROM {table_name} ORDER BY timestamp DESC")
        data_list = cursor.fetchall()
        app.logger.info(f"Helper fetch_data_as_df: Fetched {len(data_list)} rows from {table_name}.")
        if not data_list: return pd.DataFrame()
        return pd.DataFrame(data_list)
    except MySQLError as e:
        app.logger.error(f"Helper fetch_data_as_df: DB Error fetching from {table_name}: {e}", exc_info=True)
        return None
    except Exception as e:
        app.logger.error(f"Helper fetch_data_as_df: Unexpected error fetching from {table_name}: {e}", exc_info=True)
        return None
    finally:
        if cursor: cursor.close()
        if db_conn and db_conn.is_connected():
            db_conn.close()
            app.logger.debug(f"Helper fetch_data_as_df: Closed direct DB connection for {table_name}.")

@app.route('/admin/download_raw_annotations')
def download_raw_annotations():
    """Downloads the raw annotation data (results_cross table)."""
    app.logger.warning("Accessed unsecured /admin/download_raw_annotations route.")
    df = fetch_data_as_df(RESULTS_TABLE_CROSS)
    if df is None: flash(f"Error fetching raw annotations data. Check logs.", "error"); return redirect(url_for('admin_view'))
    if df.empty: flash(f"Annotations table ('{RESULTS_TABLE_CROSS}') is empty.", "warning"); return redirect(url_for('admin_view'))
    try:
        buffer = io.BytesIO()
        buffer.write(df.to_csv(index=False, encoding='utf-8').encode('utf-8'))
        buffer.seek(0)
        app.logger.info(f"Sending raw annotations CSV download ({len(df)} rows).")
        return send_file(buffer, mimetype='text/csv', download_name='raw_cross_annotations.csv', as_attachment=True)
    except Exception as e:
        app.logger.error(f"Download raw annotations: Error generating CSV: {e}", exc_info=True)
        flash(f"Error preparing raw annotations download: {e}", "error")
        return redirect(url_for('admin_view'))

@app.route('/admin/download_familiarity')
def download_familiarity_ratings():
    """Downloads the familiarity ratings."""
    app.logger.warning("Accessed unsecured /admin/download_familiarity route.")
    df = fetch_data_as_df(FAMILIARITY_TABLE)
    if df is None: flash(f"Error fetching familiarity ratings data. Check logs.", "error"); return redirect(url_for('admin_view'))
    if df.empty: flash(f"Familiarity ratings table ('{FAMILIARITY_TABLE}') is empty.", "warning"); return redirect(url_for('admin_view'))
    try:
        buffer = io.BytesIO()
        buffer.write(df.to_csv(index=False, encoding='utf-8').encode('utf-8'))
        buffer.seek(0)
        app.logger.info(f"Sending familiarity ratings CSV download ({len(df)} rows).")
        return send_file(buffer, mimetype='text/csv', download_name='familiarity_ratings.csv', as_attachment=True)
    except Exception as e:
        app.logger.error(f"Download familiarity: Error generating CSV: {e}", exc_info=True)
        flash(f"Error preparing familiarity download: {e}", "error")
        return redirect(url_for('admin_view'))


# --- Main Execution ---
if __name__ == '__main__':
    app.logger.info(f"Initializing database '{MYSQL_DB}'...")
    with app.app_context():
        init_db()
    app.logger.info("Starting Flask application (Cross-State Version)...")
    host = os.environ.get('FLASK_RUN_HOST', '127.0.0.1')
    try: port = int(os.environ.get('FLASK_RUN_PORT', '5001'))
    except ValueError: port = 5001
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    if not debug_mode: app.logger.warning("FLASK_ENV not 'development'. Running dev server without debug.")
    # Set debug=False in production environment variable (FLASK_ENV=production)
    app.run(host=host, port=port, debug=debug_mode)