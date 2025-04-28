# -*- coding: utf-8 -*-
# stereotype_quiz_app/app.py (Cross-State Version - Refactored)

import os
import csv
import io
import random
import mysql.connector
from mysql.connector import Error as MySQLError
from flask import (Flask, render_template, request, redirect, url_for, g,
                   flash, Response, send_file, session, current_app)
import pandas as pd
import numpy as np
from dotenv import load_dotenv
import logging
import sys
import traceback

# --- Load Environment Variables ---
# Loads .env file for local development ONLY. Ignored by PythonAnywhere.
load_dotenv()

# --- Configuration ---
CSV_FILE_PATH = os.path.join('data', 'stereotypes.csv')
# Schema file MUST define BOTH results_cross AND familiarity_ratings tables
SCHEMA_FILE = 'schema.sql'

# --- Load Config from Environment Variables ---
SECRET_KEY = os.environ.get('SECRET_KEY')
MYSQL_HOST = os.environ.get('MYSQL_HOST')
MYSQL_USER = os.environ.get('MYSQL_USER')
MYSQL_PASSWORD = os.environ.get('MYSQL_PASSWORD')
MYSQL_DB = os.environ.get('MYSQL_DB') # Should match your cross-state DB name (e.g., stereotype_cross)
MYSQL_PORT = int(os.environ.get('MYSQL_PORT', 3306))

# Define table names used in this version (readability)
RESULTS_TABLE_CROSS = 'results_cross'
FAMILIARITY_TABLE = 'familiarity_ratings'

# --- Flask App Initialization ---
app = Flask(__name__)
# Load configuration into Flask app config
app.config['SECRET_KEY'] = SECRET_KEY
app.config['MYSQL_HOST'] = MYSQL_HOST
app.config['MYSQL_USER'] = MYSQL_USER
app.config['MYSQL_PASSWORD'] = MYSQL_PASSWORD
app.config['MYSQL_DB'] = MYSQL_DB
app.config['MYSQL_PORT'] = MYSQL_PORT
# Optional: Production session cookie settings
# app.config['SESSION_COOKIE_SECURE'] = True
# app.config['SESSION_COOKIE_HTTPONLY'] = True
# app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]')
app.logger.setLevel(logging.INFO) # Set Flask's logger level

app.logger.info("Flask application (Cross-State Version) starting...")

# --- Configuration Validation ---
if not SECRET_KEY:
    app.logger.critical("CRITICAL ERROR: SECRET_KEY not set. Flask sessions WILL NOT WORK.")
# Check essential DB config (password can be empty string locally, but check others)
if not all([MYSQL_HOST, MYSQL_USER, MYSQL_DB]):
    app.logger.critical("CRITICAL ERROR: Essential Database configuration (HOST, USER, DB) missing in environment variables.")
else:
    app.logger.info(f"Database config loaded: Host={MYSQL_HOST}, User={MYSQL_USER}, DB={MYSQL_DB}, Port={MYSQL_PORT}")


# --- Database Functions ---
def get_db():
    """Opens/returns DB connection & cursor for the request context (g)."""
    if 'db' not in g:
        try:
            g.db = mysql.connector.connect(
                host=current_app.config['MYSQL_HOST'],
                user=current_app.config['MYSQL_USER'],
                password=current_app.config['MYSQL_PASSWORD'],
                database=current_app.config['MYSQL_DB'],
                port=current_app.config['MYSQL_PORT'],
                autocommit=False, # Use manual commits/rollbacks
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
    """Closes DB connection & cursor at end of request."""
    cursor = g.pop('cursor', None)
    if cursor:
        try: cursor.close()
        except Exception as e: app.logger.warning(f"Error closing cursor: {e}")
    db = g.pop('db', None)
    if db and db.is_connected():
        try: db.close(); app.logger.debug("Request DB connection closed.")
        except Exception as e: app.logger.warning(f"Error closing DB connection: {e}")
    if error:
        app.logger.error(f"App context teardown error: {error}", exc_info=True)

def init_db():
    """Checks required tables exist, executes schema if needed. Best run manually."""
    db_host = current_app.config['MYSQL_HOST']; db_user = current_app.config['MYSQL_USER']
    db_password = current_app.config['MYSQL_PASSWORD']; db_name = current_app.config['MYSQL_DB']
    db_port = current_app.config['MYSQL_PORT']
    if not all([db_host, db_user, db_name]): # Password can be empty locally
        app.logger.error("Cannot initialize DB: Core configuration missing.")
        return False

    temp_conn = None; temp_cursor = None
    app.logger.info(f"Checking database '{db_name}' table setup...")
    required_tables = [RESULTS_TABLE_CROSS, FAMILIARITY_TABLE]
    tables_exist = {table: False for table in required_tables}
    schema_executed_successfully = False

    try:
        # Connect using separate connection for setup
        temp_conn = mysql.connector.connect(host=db_host, user=db_user, password=db_password, database=db_name, port=db_port, connection_timeout=10)
        temp_cursor = temp_conn.cursor()

        # Check existence of each required table
        for table_name in required_tables:
            app.logger.debug(f"Checking for table '{table_name}'...")
            temp_cursor.execute(f"SHOW TABLES LIKE '{table_name}'")
            if temp_cursor.fetchone():
                tables_exist[table_name] = True
                app.logger.info(f"Table '{table_name}' already exists.")
            else:
                app.logger.warning(f"Table '{table_name}' not found.")

        # If any table is missing, attempt to run the schema file
        if not all(tables_exist.values()):
            app.logger.warning(f"One or more tables missing. Executing schema '{SCHEMA_FILE}'...")
            schema_path = os.path.join(current_app.root_path, SCHEMA_FILE)
            if not os.path.exists(schema_path):
                 app.logger.error(f"FATAL: Schema file '{SCHEMA_FILE}' not found at: {schema_path}")
                 return False # Cannot proceed without schema

            try:
                with open(schema_path, mode='r', encoding='utf-8') as f: sql_script = f.read()
                app.logger.info(f"Executing SQL script from {schema_path}...")
                # Execute script, handling multiple statements; requires multi=True
                for result in temp_cursor.execute(sql_script, multi=True):
                    # Log results of each statement if needed
                    app.logger.debug(f"Schema exec: Stmt='{result.statement[:60]}...', Rows={result.rowcount}, Warnings={result.fetchwarnings()}")
                    if result.with_rows: result.fetchall() # Consume results
                temp_conn.commit() # Commit transaction after successful execution
                schema_executed_successfully = True
                app.logger.info(f"Schema '{SCHEMA_FILE}' executed successfully and committed.")
                # Re-check table existence after execution
                for table_name in required_tables:
                     temp_cursor.execute(f"SHOW TABLES LIKE '{table_name}'")
                     if temp_cursor.fetchone(): tables_exist[table_name] = True

            except MySQLError as err:
                app.logger.error(f"Error executing schema file '{SCHEMA_FILE}': {err}", exc_info=True)
                try: temp_conn.rollback() # Rollback on error
                except Exception as rb_err: app.logger.error(f"Rollback failed after schema error: {rb_err}")
            except Exception as e:
                app.logger.error(f"Unexpected error initializing schema from file: {e}", exc_info=True)
                try: temp_conn.rollback()
                except Exception as rb_err: app.logger.error(f"Rollback failed after schema error: {rb_err}")
        else:
            app.logger.info("All required database tables already exist.")

    except MySQLError as err:
        # Errors connecting to DB or running initial checks
        app.logger.error(f"Error during DB connection/check for initialization: {err}", exc_info=True)
    except Exception as e:
        app.logger.error(f"Unexpected error during DB initialization phase: {e}", exc_info=True)
    finally:
        # Ensure temporary connection is closed
        if temp_cursor: temp_cursor.close()
        if temp_conn and temp_conn.is_connected(): temp_conn.close()
        app.logger.debug("DB init connection closed.")

    # Return status indicating if all required tables now exist
    final_status = all(tables_exist.values())
    if not final_status:
         app.logger.error("Database initialization failed: Not all required tables exist after check/execution.")
    return final_status


# --- Data Loading Function ---
def load_stereotype_data(relative_filepath=CSV_FILE_PATH):
    """Loads stereotype definitions from the CSV."""
    stereotype_data = []
    # Determine base path safely, works inside/outside app context
    base_path = getattr(current_app, 'root_path', None) or os.path.dirname(os.path.abspath(__file__))
    full_filepath = os.path.join(base_path, relative_filepath)
    # Use app logger if available, otherwise default Python logger
    logger = getattr(current_app, 'logger', logging.getLogger(__name__))
    logger.info(f"Attempting to load stereotype data from: {full_filepath}")
    try:
        if not os.path.exists(full_filepath): raise FileNotFoundError(f"{full_filepath}")
        with open(full_filepath, mode='r', encoding='utf-8-sig') as infile: # Handle BOM
            reader = csv.DictReader(infile)
            required_cols = ['State', 'Category', 'Superset', 'Subsets'] # Define expected columns
            if not reader.fieldnames or not all(field in reader.fieldnames for field in required_cols):
                 missing = [c for c in required_cols if c not in (reader.fieldnames or [])]
                 raise ValueError(f"CSV missing required columns: {missing}. Found: {reader.fieldnames}")
            for i, row in enumerate(reader):
                try:
                    # Extract and clean data, provide defaults if necessary
                    state = row.get('State','').strip(); category = row.get('Category','Uncategorized').strip()
                    superset = row.get('Superset','').strip(); subsets_str = row.get('Subsets','')
                    if not state or not superset: continue # Skip rows missing essential data
                    subsets = sorted([s.strip() for s in subsets_str.split(',') if s.strip()])
                    stereotype_data.append({'state': state, 'category': category, 'superset': superset, 'subsets': subsets})
                except Exception as row_err:
                    logger.warning(f"Error processing stereotype CSV row {i+1}: {row_err}")
                    continue # Skip problematic row
        logger.info(f"Successfully loaded {len(stereotype_data)} stereotype entries.")
        return stereotype_data
    except FileNotFoundError as e:
        logger.critical(f"FATAL: Stereotype CSV file not found: {e}")
        return []
    except ValueError as ve:
        logger.critical(f"FATAL: Error processing stereotype CSV headers/structure: {ve}")
        return []
    except Exception as e:
        logger.critical(f"FATAL: Unexpected error loading stereotype data: {e}", exc_info=True)
        return []

# --- Load Data & Get List of States ---
# Use with app.app_context() to ensure current_app is available for logger/path
with app.app_context():
    ALL_STEREOTYPE_DATA = load_stereotype_data()
    if ALL_STEREOTYPE_DATA:
        ALL_DEFINED_STATES = sorted(list(set(item['state'] for item in ALL_STEREOTYPE_DATA)))
        app.logger.info(f"Stereotype data loaded. States available ({len(ALL_DEFINED_STATES)} unique).")
    else:
        app.logger.error("CRITICAL: Stereotype data loading failed! Quiz functionality will be impaired.")
        ALL_DEFINED_STATES = ["Error: State Data Load Failed"]


# --- Flask Routes ---

@app.route('/', methods=['GET', 'POST'])
def index():
    """Handles the initial user info form page."""
    if request.method == 'POST':
        user_name = request.form.get('name', '').strip()
        native_state = request.form.get('native_state')
        user_age_str = request.form.get('age')
        user_sex = request.form.get('sex')

        errors = False
        if not user_name: flash('Name is required.', 'error'); errors = True
        # Check if states loaded correctly before validating selection
        if "Error: State Data Load Failed" in ALL_DEFINED_STATES:
            flash('Application Error: Cannot load state data. Please contact support.', 'error')
            # Stop validation if states aren't loaded
            return render_template('index.html', states=ALL_DEFINED_STATES, form_data=request.form, error_state=True)
        elif not native_state or native_state not in ALL_DEFINED_STATES:
            flash('Please select your valid native state.', 'error'); errors = True

        if not user_sex: flash('Please select your sex.', 'error'); errors = True

        user_age = None
        # --- MANDATORY AGE VALIDATION ---
        if not user_age_str:
             flash('Age is required.', 'error'); errors = True
        else: # Only validate if provided
            try:
                user_age = int(user_age_str)
                if user_age < 1: # Optional check
                     flash('Please enter a valid age.', 'error'); errors = True
            except ValueError:
                flash('Please enter a valid number for age.', 'error'); errors = True

        if errors:
            return render_template('index.html', states=ALL_DEFINED_STATES, form_data=request.form)

        # --- Passed Validation - Setup Session ---
        session.clear()
        session['user_name'] = user_name
        session['native_state'] = native_state
        session['user_age'] = user_age
        session['user_sex'] = user_sex

        target_states = [s for s in ALL_DEFINED_STATES if s != native_state]
        if not target_states:
            app.logger.info(f"User '{user_name}' (Native: {native_state}) has no target states.")
            flash("No other states found to annotate for your native state. Thank you!", 'info')
            return redirect(url_for('thank_you'))

        random.shuffle(target_states)
        session['target_states'] = target_states
        session['current_state_index'] = 0
        session.modified = True # Ensure session changes are saved

        app.logger.info(f"User '{user_name}' (Native: {native_state}) starting quiz. Target states: {len(target_states)}.")
        return redirect(url_for('quiz_cross'))

    # --- GET Request ---
    session.clear() # Ensure clean state on new visit
    if "Error: State Data Load Failed" in ALL_DEFINED_STATES:
        flash("Application Error: Could not load state data.", "error")
        return render_template('index.html', states=ALL_DEFINED_STATES, form_data={}, error_state=True)
    return render_template('index.html', states=ALL_DEFINED_STATES, form_data={})


@app.route('/quiz', methods=['GET', 'POST'])
def quiz_cross():
    """Handles sequential display and submission for each target state."""
    required_session_keys = ['user_name', 'native_state', 'target_states', 'current_state_index']
    if not all(key in session for key in required_session_keys):
        app.logger.warning("Invalid session state in /quiz. Redirecting to index.")
        flash('Your session has expired or is invalid. Please start again.', 'warning')
        return redirect(url_for('index'))

    target_states = session['target_states']
    current_index = session['current_state_index']

    # Check if quiz is complete
    if current_index >= len(target_states):
        app.logger.info(f"User '{session['user_name']}' finished all {len(target_states)} states.")
        return redirect(url_for('thank_you'))

    current_target_state = target_states[current_index]
    app.logger.debug(f"Processing quiz for state index {current_index}: {current_target_state}")

    # --- Handle POST (Save data for the state just completed) ---
    if request.method == 'POST':
        app.logger.info(f"POST received for state index {current_index} ({current_target_state})")
        cursor = get_db()
        if not cursor:
            app.logger.error("Quiz POST failed: Could not get DB cursor.")
            flash("Database connection error. Please try again.", "error")
            # Don't advance, try the same state again
            return redirect(url_for('quiz_cross'))
        db_connection = g.db # Needed for commit/rollback

        try:
            # --- 1. Validate and Insert Familiarity Rating ---
            familiarity_rating_str = request.form.get('familiarity_rating')
            if familiarity_rating_str is None:
                 app.logger.error("Submission error: Familiarity rating missing from POST.")
                 flash('Error: Familiarity rating is required. Please try again.', 'error')
                 return redirect(url_for('quiz_cross')) # Stay on same state

            try:
                familiarity_rating = int(familiarity_rating_str)
                if not (0 <= familiarity_rating <= 5): raise ValueError("Rating out of range")
            except (ValueError, TypeError):
                app.logger.error(f"Invalid familiarity rating '{familiarity_rating_str}' submitted.")
                flash('Invalid familiarity rating (must be 0-5).', 'error')
                return redirect(url_for('quiz_cross')) # Stay on same state

            app.logger.info(f"Attempting to insert familiarity rating ({familiarity_rating}) for {current_target_state}...")
            fam_sql = f"""INSERT INTO {FAMILIARITY_TABLE}
                          (native_state, target_state, familiarity_rating, user_name, user_age, user_sex)
                          VALUES (%(native_state)s, %(target_state)s, %(rating)s, %(name)s, %(age)s, %(sex)s)"""
            fam_data = {'native_state': session['native_state'], 'target_state': current_target_state,
                        'rating': familiarity_rating, 'name': session['user_name'],
                        'age': session.get('user_age'), 'sex': session.get('user_sex')}
            cursor.execute(fam_sql, fam_data)
            fam_rowcount = cursor.rowcount
            app.logger.info(f"Familiarity inserted (rowcount={fam_rowcount}, pre-commit).")

            # --- 2. Prepare and Insert Stereotype Annotations ---
            annotations_to_insert = []
            # ***** Retrieve num_quiz_items from the form (expects hidden input in HTML) *****
            num_items_on_page_str = request.form.get('num_quiz_items')
            if num_items_on_page_str is None:
                 # Log critical error if the hidden field wasn't submitted
                 app.logger.critical(f"CRITICAL ERROR: Hidden input 'num_quiz_items' not found in form submission for state {current_target_state}. Annotations WILL NOT be saved.")
                 flash("A form processing error occurred (missing item count). Progress for this state may be lost. Please try again.", 'error')
                 db_connection.rollback() # Rollback the familiarity rating insert
                 return redirect(url_for('quiz_cross')) # Stay on same page to allow retry

            try:
                 num_items_on_page = int(num_items_on_page_str)
            except ValueError:
                 app.logger.critical(f"CRITICAL ERROR: Invalid value received for 'num_quiz_items': '{num_items_on_page_str}' for state {current_target_state}. Annotations WILL NOT be saved.")
                 flash("A form processing error occurred (invalid item count). Progress for this state may be lost. Please try again.", 'error')
                 db_connection.rollback() # Rollback the familiarity rating insert
                 return redirect(url_for('quiz_cross')) # Stay on same page

            # ***** End section retrieving num_quiz_items *****

            app.logger.debug(f"Parsing annotations for {num_items_on_page} items.")

            for i in range(num_items_on_page): # Loop based on submitted count
                identifier = str(i)
                superset = request.form.get(f'superset_{identifier}')
                category = request.form.get(f'category_{identifier}')
                annotation = request.form.get(f'annotation_{identifier}')

                # Basic validation for required fields per item
                if not annotation or not superset or not category:
                    app.logger.warning(f"Skipping annotation item index {identifier} on state {current_target_state}: missing required form data (Annotation/Superset/Category).")
                    # If this happens despite client-side validation, it could indicate a form structure issue or manipulation.
                    # Consider if this should halt the entire submission:
                    # flash(f"Incomplete data received for item {i+1}. Submission cancelled.", 'error')
                    # db_connection.rollback()
                    # return redirect(url_for('quiz_cross'))
                    continue # Default: Skip this specific item

                offensiveness = -1 # Default value
                if annotation == 'Stereotype':
                    rating_str = request.form.get(f'offensiveness_{identifier}')
                    if rating_str is not None and rating_str.isdigit():
                        rating_val = int(rating_str)
                        if 0 <= rating_val <= 5:
                            offensiveness = rating_val
                        else:
                            app.logger.warning(f"Annotation item {identifier} for state {current_target_state}: Out-of-range rating ({rating_val}). Defaulting to -1.")
                    elif rating_str is not None: # Submitted but not a digit
                        app.logger.warning(f"Annotation item {identifier} for state {current_target_state}: Non-integer rating ('{rating_str}'). Defaulting to -1.")
                    else:
                        # Should be caught by client validation if 'Stereotype' is checked
                         app.logger.error(f"Annotation item {identifier} for state {current_target_state}: Offensiveness rating missing despite 'Stereotype' selection. Defaulting to -1.")
                         # Offensiveness remains -1

                annotations_to_insert.append({
                    'native_state': session['native_state'], 'target_state': current_target_state,
                    'user_name': session['user_name'], 'user_age': session.get('user_age'),
                    'user_sex': session.get('user_sex'), 'category': category,
                    'attribute_superset': superset, 'annotation': annotation,
                    'offensiveness_rating': offensiveness
                })

            # --- Execute annotation insert (if any) ---
            annotations_rowcount = 0
            if annotations_to_insert:
                # Optional: Check if number parsed matches expected number
                if len(annotations_to_insert) != num_items_on_page:
                     app.logger.warning(f"Mismatch: Expected {num_items_on_page} items, but parsed {len(annotations_to_insert)} valid annotations for state {current_target_state}.")

                app.logger.info(f"Attempting to insert {len(annotations_to_insert)} annotations for {current_target_state}...")
                results_sql = f"""INSERT INTO {RESULTS_TABLE_CROSS}
                                  (native_state, target_state, user_name, user_age, user_sex, category, attribute_superset, annotation, offensiveness_rating)
                                  VALUES (%(native_state)s, %(target_state)s, %(user_name)s, %(user_age)s, %(user_sex)s, %(category)s, %(attribute_superset)s, %(annotation)s, %(offensiveness_rating)s)"""
                try:
                     cursor.executemany(results_sql, annotations_to_insert)
                     annotations_rowcount = cursor.rowcount # Get rowcount immediately after execute
                     app.logger.info(f"Annotation insertion executemany completed (Reported rowcount={annotations_rowcount}, pre-commit) for state {current_target_state}.")
                     # Note: cursor.rowcount for executemany might be -1 or sum depending on driver/settings. Log actual list length for certainty.
                except MySQLError as exec_many_err:
                    app.logger.error(f"DB Error during annotation executemany for state {current_target_state}: {exec_many_err}", exc_info=True)
                    app.logger.error(f"Data attempted (first record if any): {annotations_to_insert[0] if annotations_to_insert else 'N/A'}")
                    flash("Database error saving your detailed responses. Please try again.", 'error');
                    db_connection.rollback() # Rollback everything for this state
                    return redirect(url_for('quiz_cross')) # Stay on the same page

            elif num_items_on_page > 0: # Items existed, but none were valid to insert
                app.logger.warning(f"No valid annotations were inserted for state {current_target_state} (expected {num_items_on_page} items). Only familiarity rating will be committed.")
                # Consider if this scenario requires a rollback or specific user feedback
            else: # num_items_on_page was 0
                app.logger.info(f"No quiz items were presented for state {current_target_state} (num_items_on_page=0), skipping annotation insert.")


            # --- 3. Commit Transaction ---
            app.logger.info(f"Attempting commit for state {current_target_state} (Familiarity Inserted: {fam_rowcount > 0}, Annotations Attempted: {len(annotations_to_insert)})")
            db_connection.commit() # Commit familiarity and any successful annotation inserts
            app.logger.info(f"COMMIT successful for state {current_target_state}.")

            # --- 4. Advance Session State ---
            session['current_state_index'] = current_index + 1
            session.modified = True # Mark session as modified
            app.logger.info(f"Advancing user '{session['user_name']}' to state index {session['current_state_index']}.")
            return redirect(url_for('quiz_cross'))

        # --- Handle Errors During POST ---
        except MySQLError as db_err:
            app.logger.error(f"DB Transaction Error saving data for state {current_target_state}: {db_err}", exc_info=True)
            try:
                if db_connection and db_connection.is_connected(): # Check if connection exists and is open
                     db_connection.rollback();
                     app.logger.info("Rolled back transaction due to DB error.")
            except Exception as rb_err: app.logger.error(f"Rollback failed after DB error: {rb_err}")
            flash("A database error occurred while saving. Please try submitting this state again.", 'error')
            return redirect(url_for('quiz_cross')) # Stay on same state

        except Exception as e:
            app.logger.error(f"Unexpected error processing POST for state {current_target_state}: {e}", exc_info=True)
            try:
                 if db_connection and db_connection.is_connected(): # Check if connection exists and is open
                     db_connection.rollback();
                     app.logger.info("Rolled back transaction due to unexpected error.")
            except Exception as rb_err: app.logger.error(f"Rollback failed after unexpected error: {rb_err}")
            flash("An unexpected server error occurred. Please start the quiz again.", 'error')
            return redirect(url_for('index')) # Go back to start


    # --- Handle GET Request (Display Quiz Page) ---
    app.logger.info(f"GET request for state index {current_index} ({current_target_state})")
    if "Error: State Data Load Failed" in ALL_DEFINED_STATES:
         app.logger.error("Cannot display quiz page because state data failed to load.")
         flash("Application error: Cannot load stereotype data.", "error")
         return redirect(url_for('index'))

    quiz_items_for_state = [item for item in ALL_STEREOTYPE_DATA if item.get('state') == current_target_state] # Use .get for safety
    # Optional: Sort items for consistent display order
    quiz_items_for_state.sort(key=lambda x: (x.get('category', ''), x.get('superset', '')))

    is_last_state = (current_index == len(target_states) - 1)
    num_items_to_display = len(quiz_items_for_state)
    app.logger.debug(f"Rendering quiz for {current_target_state}. Items: {num_items_to_display}. Last State: {is_last_state}")

    return render_template('quiz.html',
                           target_state=current_target_state,
                           quiz_items=quiz_items_for_state,
                           user_info=session, # Pass relevant session info
                           current_index=current_index,
                           total_states=len(target_states),
                           is_last_state=is_last_state,
                           # Pass the count to be used in the hidden field in the template
                           num_quiz_items=num_items_to_display)


@app.route('/thank_you')
def thank_you():
    """Displays the thank you page."""
    user_name = session.get('user_name', 'Participant') # Get name from session if available
    app.logger.info(f"Displaying thank you page for user '{user_name}'.")
    # Optionally clear session here if the quiz is truly over
    # session.clear()
    return render_template('thank_you.html', user_name=user_name)


# --- Admin Routes ---
# !! SECURITY WARNING: Add authentication before deploying to production !!
@app.route('/admin')
def admin_view():
    """Displays raw annotation results and familiarity ratings."""
    app.logger.info("Admin route entered.")
    app.logger.warning("Accessed unsecured /admin route.")
    cursor = get_db()
    if not cursor:
        app.logger.error("Admin view failed: Could not get DB cursor.")
        return redirect(url_for('index')) # Error flashed by get_db

    results_data = []; familiarity_data = []
    try:
        # Fetch cross annotations
        app.logger.info(f"Admin view: Fetching data from {RESULTS_TABLE_CROSS}...")
        cursor.execute(f"SELECT * FROM {RESULTS_TABLE_CROSS} ORDER BY timestamp DESC")
        results_data = cursor.fetchall()
        app.logger.info(f"Admin view: Fetched {len(results_data)} annotations.")

        # Fetch familiarity ratings
        app.logger.info(f"Admin view: Fetching data from {FAMILIARITY_TABLE}...")
        cursor.execute(f"SELECT * FROM {FAMILIARITY_TABLE} ORDER BY timestamp DESC")
        familiarity_data = cursor.fetchall()
        app.logger.info(f"Admin view: Fetched {len(familiarity_data)} familiarity ratings.")

    except MySQLError as err:
        app.logger.error(f"Admin view: Error fetching data: {err}", exc_info=True)
        flash('Error fetching results from database.', 'error')
        # Still render template but indicate tables might be empty/error occurred
        results_data = []; familiarity_data = []
    except Exception as e:
        app.logger.error(f"Admin view: Unexpected error fetching data: {e}", exc_info=True)
        flash('An unexpected error occurred loading admin data.', 'error')
        results_data = []; familiarity_data = []

    app.logger.debug("Admin view: Rendering template.")
    # Ensure admin.html template can handle both lists
    return render_template('admin.html', results=results_data, familiarity_ratings=familiarity_data)

# --- REFACTORED Download Routes Helper ---
def fetch_data_as_df(table_name):
    """Helper: Fetches all data from a table into a DataFrame using direct connection."""
    app.logger.info(f"Helper: Attempting to fetch data from '{table_name}'")
    db_conn = None; cursor = None; data_list = []
    try:
        # Get config safely
        db_host = current_app.config.get('MYSQL_HOST'); db_user = current_app.config.get('MYSQL_USER')
        db_password = current_app.config.get('MYSQL_PASSWORD'); db_name = current_app.config.get('MYSQL_DB')
        db_port = current_app.config.get('MYSQL_PORT')
        if not all([db_host, db_user, db_name]): # Password can be empty/None
             app.logger.error(f"Helper fetch: DB config incomplete for {table_name}.")
             return None # Indicate config error

        app.logger.debug(f"Helper fetch: Connecting directly to DB for {table_name}...")
        db_conn = mysql.connector.connect(
            host=db_host, user=db_user, password=db_password, database=db_name, port=db_port, connection_timeout=10
        )
        cursor = db_conn.cursor(dictionary=True) # Fetch rows as dictionaries
        query = f"SELECT * FROM {table_name} ORDER BY timestamp DESC"
        app.logger.debug(f"Helper fetch: Executing query: {query}")
        cursor.execute(query)
        data_list = cursor.fetchall()
        app.logger.info(f"Helper fetch: Fetched {len(data_list)} rows from {table_name}.")
        if not data_list:
             app.logger.warning(f"Helper fetch: No data found in table {table_name}.")
             return pd.DataFrame() # Return empty DataFrame is valid if table is empty
        # Convert list of dictionaries to DataFrame
        return pd.DataFrame(data_list)
    except MySQLError as e:
        app.logger.error(f"Helper fetch: DB Error for {table_name}: {e}", exc_info=True)
        return None # Indicate database error
    except Exception as e:
        app.logger.error(f"Helper fetch: Unexpected error for {table_name}: {e}", exc_info=True)
        return None # Indicate other error
    finally:
        # Ensure resources are closed
        if cursor: cursor.close()
        if db_conn and db_conn.is_connected():
            db_conn.close()
            app.logger.debug(f"Helper fetch: Closed direct DB connection for {table_name}.")

@app.route('/admin/download_raw_annotations')
def download_raw_annotations():
    """Downloads the raw annotation data (results_cross table)."""
    app.logger.warning("Accessed unsecured /admin/download_raw_annotations route.")
    df = fetch_data_as_df(RESULTS_TABLE_CROSS)

    if df is None: # Indicates an error during fetch
        flash(f"Error fetching raw annotations data from '{RESULTS_TABLE_CROSS}'. Check server logs.", "error")
        return redirect(url_for('admin_view'))
    if df.empty:
        flash(f"Annotations table ('{RESULTS_TABLE_CROSS}') appears to be empty. Nothing to download.", "warning")
        return redirect(url_for('admin_view'))

    try:
        buffer = io.BytesIO()
        # Ensure correct encoding for CSV content (utf-8-sig often preferred for Excel)
        buffer.write(df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig'))
        buffer.seek(0)
        app.logger.info(f"Sending raw annotations CSV download ({len(df)} rows).")
        return send_file(buffer, mimetype='text/csv', download_name='raw_cross_annotations.csv', as_attachment=True)
    except Exception as e:
        app.logger.error(f"Download raw annotations: Error generating CSV: {e}", exc_info=True)
        flash(f"Error preparing raw annotations download file: {e}", "error")
        return redirect(url_for('admin_view'))

@app.route('/admin/download_familiarity')
def download_familiarity_ratings():
    """Downloads the familiarity ratings."""
    app.logger.warning("Accessed unsecured /admin/download_familiarity route.")
    df = fetch_data_as_df(FAMILIARITY_TABLE)

    if df is None: # Indicates an error during fetch
        flash(f"Error fetching familiarity ratings data from '{FAMILIARITY_TABLE}'. Check server logs.", "error")
        return redirect(url_for('admin_view'))
    if df.empty:
        flash(f"Familiarity ratings table ('{FAMILIARITY_TABLE}') appears to be empty. Nothing to download.", "warning")
        return redirect(url_for('admin_view'))

    try:
        buffer = io.BytesIO()
        # Ensure correct encoding for CSV content (utf-8-sig often preferred for Excel)
        buffer.write(df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig'))
        buffer.seek(0)
        app.logger.info(f"Sending familiarity ratings CSV download ({len(df)} rows).")
        return send_file(buffer, mimetype='text/csv', download_name='familiarity_ratings.csv', as_attachment=True)
    except Exception as e:
        app.logger.error(f"Download familiarity: Error generating CSV: {e}", exc_info=True)
        flash(f"Error preparing familiarity download file: {e}", "error")
        return redirect(url_for('admin_view'))


# --- Main Execution (for Local Development ONLY) ---
if __name__ == '__main__':
    app.logger.info(f"Attempting to initialize database '{MYSQL_DB}' (if necessary)...")
    # Run init_db within app context to ensure config is loaded
    with app.app_context():
        db_ok = init_db()
        if not db_ok:
             app.logger.warning("Database initialization check reported issues. App may not function correctly.")
             # Consider whether to proceed if DB init fails locally

    app.logger.info("Starting Flask development server (Cross-State Version)...")
    # Read host/port from environment, defaulting for local dev
    host = os.environ.get('FLASK_RUN_HOST', '127.0.0.1') # Default to localhost
    try:
        port = int(os.environ.get('FLASK_RUN_PORT', '5001')) # Use different default port
    except ValueError:
        port = 5001
        app.logger.warning(f"Invalid FLASK_RUN_PORT value. Using default {port}.")

    # Enable Flask debug mode ONLY if FLASK_ENV is explicitly 'development'
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    if debug_mode:
        app.logger.warning("Flask development server running in DEBUG mode.")
    else:
        app.logger.warning("FLASK_ENV is not 'development'. Running dev server without debug mode.")
        app.logger.warning("For production deployment, use a WSGI server (like Gunicorn via PythonAnywhere) and set FLASK_ENV=production.")

    # Start the development server
    app.run(host=host, port=port, debug=debug_mode)