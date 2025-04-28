# stereotype_quiz_app/app_cross_state.py
# Version 2: Cross-State Stereotype Annotation Quiz

import os
import csv
import io         # For in-memory file handling
import random     # To shuffle states
import mysql.connector
from mysql.connector import Error as MySQLError
from flask import (Flask, render_template, request, redirect, url_for, g,
                   flash, Response, send_file, session) # Added session
import pandas as pd
import numpy as np

# --- Configuration ---
# CSV Definitions File (relative to app.py)
CSV_FILE_PATH = os.path.join('data', 'stereotypes.csv')
# Schema file for THIS version (must define results_cross AND familiarity_ratings tables)
SCHEMA_FILE = 'schema.sql' #schema_mysql_cross Use the new schema file name

# Flask Secret Key (Essential for session management - CHANGE IN PRODUCTION)
SECRET_KEY = 'respai' # As provided by user

# --- MySQL Configuration (NEW Database Name, User Provided Password) ---
MYSQL_HOST = 'localhost'
MYSQL_USER = 'stereotype_user'
MYSQL_PASSWORD = 'RespAI@2025' # As provided by user
MYSQL_DB = 'stereotype_cross' # *** NEW Database Name ***
MYSQL_PORT = 3306
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
# Optional: Configure session cookie settings for production
# app.config['SESSION_COOKIE_SECURE'] = True
# app.config['SESSION_COOKIE_HTTPONLY'] = True
# app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# --- Database Functions ---
def get_db():
    """Opens a new MySQL database connection and cursor if none exist for the current request context."""
    if 'db' not in g:
        try:
            g.db = mysql.connector.connect(
                host=app.config['MYSQL_HOST'], user=app.config['MYSQL_USER'],
                password=app.config['MYSQL_PASSWORD'], database=app.config['MYSQL_DB'],
                port=app.config['MYSQL_PORT'], autocommit=False # Disable autocommit for manual transaction control
            )
            g.cursor = g.db.cursor(dictionary=True)
        except MySQLError as err:
            print(f"Error connecting to MySQL: {err}")
            flash('Database connection error. Please contact admin.', 'error')
            g.db = None; g.cursor = None
    return getattr(g, 'cursor', None)

@app.teardown_appcontext
def close_db(error):
    """Closes the database cursor and connection at the end of the request."""
    cursor = g.pop('cursor', None)
    if cursor: cursor.close()
    db = g.pop('db', None)
    if db and db.is_connected(): db.close() # Check if connected before closing
    if error: print(f"App context teardown error: {error}")

def init_db():
    """Initializes the NEW database schema (stereotype_cross) if tables are missing."""
    temp_conn = None; temp_cursor = None
    print(f"Checking database '{app.config['MYSQL_DB']}' setup...")
    try:
        # Missing connection setup - need to add this
        temp_conn = mysql.connector.connect(
            host=app.config['MYSQL_HOST'],
            user=app.config['MYSQL_USER'],
            password=app.config['MYSQL_PASSWORD'],
            database=app.config['MYSQL_DB'],
            port=app.config['MYSQL_PORT']
        )
        temp_cursor = temp_conn.cursor()
        
        # Need to define schema_path
        base_dir = os.path.dirname(os.path.abspath(__file__))
        schema_path = os.path.join(base_dir, SCHEMA_FILE)
        
        try:
            with open(schema_path, mode='r', encoding='utf-8') as f:
                # Read the entire script
                sql_script = f.read()

            # Split the script into individual statements based on semicolon
            sql_statements = [statement.strip() for statement in sql_script.split(';') if statement.strip()]

            if not sql_statements:
                print(f"Warning: No SQL statements found in {schema_path}")
            else:
                print(f"Executing {len(sql_statements)} statements from schema...")
                # Execute each statement individually
                for statement in sql_statements:
                    try:
                        print(f"Executing: {statement[:100]}...") # Print start of statement
                        temp_cursor.execute(statement)
                    except MySQLError as stmt_err:
                        # If a statement fails (e.g., table already exists is handled by IF NOT EXISTS)
                        # print a warning but continue if possible, unless it's a critical error
                        print(f"Warning/Error executing statement: {stmt_err}")
                        # Depending on the error, you might want to break or rollback here
                        # For 'CREATE TABLE IF NOT EXISTS', errors might be less critical
                        # Raise the error to stop the whole process if needed:
                        # raise stmt_err

            temp_conn.commit() # Commit after all statements are executed successfully
            print(f"Database tables from '{SCHEMA_FILE}' created/verified successfully.")
        except FileNotFoundError:
            print(f"FATAL ERROR: Schema file '{schema_path}' not found.")
            # Optionally re-raise or exit if schema is critical
            # raise
        except MySQLError as err:
            print(f"Error executing schema file '{SCHEMA_FILE}': {err}")
            temp_conn.rollback() # Rollback any partial changes from this script
        except Exception as e:
            print(f"Unexpected error initializing schema from file: {e}")
            temp_conn.rollback()
    finally:
        if temp_cursor: temp_cursor.close()
        if temp_conn and temp_conn.is_connected(): temp_conn.close()

# --- Data Loading Function ---
def load_stereotype_data(relative_filepath=CSV_FILE_PATH):
    """Loads stereotype definitions from the CSV."""
    stereotype_data = []
    base_dir = os.path.dirname(os.path.abspath(__file__))
    full_filepath = os.path.join(base_dir, relative_filepath)
    print(f"Attempting to load stereotype data from: {full_filepath}")
    try:
        if not os.path.exists(full_filepath): raise FileNotFoundError(f"File not found: {full_filepath}")
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
                except Exception as row_err: print(f"Error processing CSV row {i+1}: {row_err}"); continue
        print(f"Successfully loaded {len(stereotype_data)} stereotype entries from {full_filepath}")
        return stereotype_data
    except FileNotFoundError: print(f"FATAL ERROR: CSV file not found at {full_filepath}."); return []
    except ValueError as ve: print(f"FATAL ERROR processing CSV: {ve}"); return []
    except Exception as e: import traceback; print(f"FATAL ERROR loading data: {e}\n{traceback.format_exc()}"); return []

# --- Load Data & Get List of States ---
ALL_STEREOTYPE_DATA = load_stereotype_data()
ALL_DEFINED_STATES = sorted(list(set(item['state'] for item in ALL_STEREOTYPE_DATA)))
if not ALL_STEREOTYPE_DATA or not ALL_DEFINED_STATES:
    print("\nCRITICAL ERROR: Stereotype data loading failed or no states found! App cannot function.\n")
    ALL_DEFINED_STATES = ["Error: Check Logs"] # Prevent crashes in templates
print(f"States available for selection/annotation: {ALL_DEFINED_STATES if 'Error' not in ALL_DEFINED_STATES[0] else 'LOADING FAILED'}")


# --- Flask Routes ---

@app.route('/', methods=['GET', 'POST'])
def index():
    """Handles the initial user info form page for cross-state annotation."""
    if request.method == 'POST':
        user_name = request.form.get('name', '').strip()
        native_state = request.form.get('native_state')
        user_age_str = request.form.get('age')
        user_sex = request.form.get('sex') # Will be 'Male' or 'Female' if selected

        errors = False
        if not user_name: flash('Name is required.', 'error'); errors = True
        if not native_state or native_state not in ALL_DEFINED_STATES:
            flash('Please select your valid native state.', 'error'); errors = True
        if not user_sex: # Check if Male or Female was selected
             flash('Please select your sex.', 'error'); errors = True

        user_age = None
        if user_age_str:
            try: user_age = int(user_age_str);
            except ValueError: flash('Please enter a valid number for age.', 'error'); errors = True

        if errors: return render_template('index.html', states=ALL_DEFINED_STATES, form_data=request.form)

        # --- Setup Session for the Quiz ---
        session.clear()
        session['user_name'] = user_name
        session['native_state'] = native_state
        session['user_age'] = user_age
        session['user_sex'] = user_sex # Store 'Male' or 'Female'

        target_states = [s for s in ALL_DEFINED_STATES if s != native_state]
        if not target_states:
            flash("No other states found to annotate. Thank you!", 'info'); return redirect(url_for('thank_you'))

        random.shuffle(target_states)
        session['target_states'] = target_states
        session['current_state_index'] = 0

        print(f"User '{user_name}' (Native: {native_state}) starting quiz. Target states: {target_states}")
        return redirect(url_for('quiz_cross')) # Redirect to the quiz route

    # GET request
    session.clear() # Clear session on fresh visit
    return render_template('index.html', states=ALL_DEFINED_STATES, form_data={})


@app.route('/quiz', methods=['GET', 'POST'])
def quiz_cross():
    """Handles the sequential display and submission for each target state."""

    # --- Validate Session ---
    if not all(key in session for key in ['user_name', 'native_state', 'target_states', 'current_state_index']):
        flash('Your session is invalid. Please start again.', 'warning')
        return redirect(url_for('index'))

    target_states = session['target_states']
    current_index = session['current_state_index']

    # --- Check if Quiz is Complete ---
    if current_index >= len(target_states):
        print(f"User '{session['user_name']}' finished all states.")
        return redirect(url_for('thank_you')) # Go to thank you page

    # Current target state based on index stored in session
    current_target_state = target_states[current_index]

    # --- Handle POST Request (Saving data for the state just completed) ---
    if request.method == 'POST':
        print(f"POST received for state index {current_index} ({current_target_state})")
        cursor = get_db()
        if not cursor: return redirect(url_for('index')) # Error should be flashed
        db_connection = g.db # Use the connection from g for transaction control

        try:
            # --- Retrieve & Validate Familiarity Rating ---
            familiarity_rating_str = request.form.get('familiarity_rating')
            if familiarity_rating_str is None:
                 # This should be prevented by client-side validation (required field)
                 flash('Error: Familiarity rating was not submitted.', 'error')
                 db_connection.rollback() # Rollback any potential partial transaction
                 # Stay on the same page to allow user to fix
                 return redirect(url_for('quiz_cross')) # Consider passing an error flag?

            try:
                familiarity_rating = int(familiarity_rating_str)
                if not (0 <= familiarity_rating <= 5): raise ValueError("Rating out of range")
            except (ValueError, TypeError):
                flash('Invalid familiarity rating submitted. Please select a value between 0 and 5.', 'error')
                print(f"Invalid familiarity rating received: '{familiarity_rating_str}'")
                db_connection.rollback()
                return redirect(url_for('quiz_cross')) # Stay on same page

            # --- Save Familiarity Rating ---
            fam_sql = f"""
                INSERT INTO {FAMILIARITY_TABLE}
                (native_state, target_state, familiarity_rating, user_name, user_age, user_sex)
                VALUES (%(native_state)s, %(target_state)s, %(rating)s, %(name)s, %(age)s, %(sex)s)
            """
            fam_data = {
                'native_state': session['native_state'], 'target_state': current_target_state,
                'rating': familiarity_rating, 'name': session['user_name'],
                'age': session.get('user_age'), 'sex': session.get('user_sex')
            }
            cursor.execute(fam_sql, fam_data)
            print(f"Saved familiarity rating ({familiarity_rating}) for {current_target_state}")

            # --- Save Stereotype Annotations ---
            annotations_to_insert = []
            processed_indices = set()
            # Check which stereotype items were *actually displayed* on the page
            # This requires hidden fields indicating which items were present.
            # Let's assume all items for the state were processed based on the loop structure.
            num_items_on_page = int(request.form.get('num_quiz_items', 0)) # Need to add this hidden field

            for i in range(num_items_on_page): # Iterate based on items presented
                identifier = str(i) # Index used in the template loop

                superset = request.form.get(f'superset_{identifier}')
                category = request.form.get(f'category_{identifier}')
                annotation = request.form.get(f'annotation_{identifier}')

                # Basic check: If annotation is missing, skip (client validation should catch this)
                if not annotation or not superset or not category:
                     print(f"Warning: Missing annotation/data for item index {identifier} on state {current_target_state}. Skipping.")
                     continue # Skip this item

                offensiveness = -1
                if annotation == 'Stereotype':
                    rating_str = request.form.get(f'offensiveness_{identifier}')
                    # Check if rating is required but missing (client validation should catch)
                    if rating_str is None:
                         print(f"Warning: Offensiveness rating missing for Stereotype item index {identifier}. Defaulting to -1.")
                         # Store -1 as required by schema, but log warning.
                    else:
                        try:
                            offensiveness = int(rating_str)
                            if not (0 <= offensiveness <= 5): offensiveness = -1
                        except: offensiveness = -1

                annotations_to_insert.append({
                    'native_state': session['native_state'], 'target_state': current_target_state,
                    'user_name': session['user_name'], 'user_age': session.get('user_age'),
                    'user_sex': session.get('user_sex'), 'category': category,
                    'attribute_superset': superset, 'annotation': annotation,
                    'offensiveness_rating': offensiveness
                })

            if annotations_to_insert:
                results_sql = f"""
                    INSERT INTO {RESULTS_TABLE_CROSS}
                    (native_state, target_state, user_name, user_age, user_sex, category, attribute_superset, annotation, offensiveness_rating)
                    VALUES (%(native_state)s, %(target_state)s, %(user_name)s, %(user_age)s, %(user_sex)s, %(category)s, %(attribute_superset)s, %(annotation)s, %(offensiveness_rating)s)
                """
                cursor.executemany(results_sql, annotations_to_insert)
                print(f"Saved {len(annotations_to_insert)} annotations for {current_target_state}")

            # Commit changes for this state (both familiarity and annotations)
            db_connection.commit()
            print(f"Committed transaction for state {current_target_state}")

            # --- Advance to Next State ---
            session['current_state_index'] = current_index + 1
            session.modified = True # Explicitly mark session as modified
            return redirect(url_for('quiz_cross'))

        except MySQLError as db_err:
             print(f"DB Error saving data for state {current_target_state}: {db_err}");
             try: db_connection.rollback() # Rollback on error
             except Exception as rb_err: print(f"Rollback failed: {rb_err}")
             flash("Database error saving responses. Please try advancing again.", 'error');
             # Redirect back to GET for the *same* state to allow retry, data wasn't saved.
             return redirect(url_for('quiz_cross'))
        except Exception as e:
             import traceback; print(f"Error processing POST for state {current_target_state}: {e}\n{traceback.format_exc()}");
             try: db_connection.rollback()
             except Exception as rb_err: print(f"Rollback failed: {rb_err}")
             flash("An unexpected error occurred processing your submission.", 'error');
             return redirect(url_for('index')) # Go back to start on unexpected error


    # --- Handle GET Request (Display current state's questions) ---
    print(f"GET request for state index {current_index} ({current_target_state})")

    quiz_items_for_state = [item for item in ALL_STEREOTYPE_DATA if item['state'] == current_target_state]
    is_last_state = (current_index == len(target_states) - 1)

    return render_template('quiz.html',
                           target_state=current_target_state,
                           quiz_items=quiz_items_for_state,
                           user_info=session, # Pass session data for context
                           current_index=current_index,
                           total_states=len(target_states),
                           is_last_state=is_last_state,
                           num_quiz_items=len(quiz_items_for_state)) # Pass number of items


@app.route('/thank_you')
def thank_you():
    """Displays the thank you page."""
    user_name = session.get('user_name', 'Participant')
    # Consider clearing session here if desired, but might be useful for debugging
    # session.clear()
    return render_template('thank_you.html', user_name=user_name)


# --- Admin Routes ---
@app.route('/admin')
def admin_view():
    """Displays raw annotation results and familiarity ratings."""
    # !! SECURITY WARNING: Add authentication !!
    cursor = get_db()
    if not cursor: return redirect(url_for('index'))
    results_data = []; familiarity_data = [] # Initialize
    try:
        cursor.execute(f"SELECT * FROM {RESULTS_TABLE_CROSS} ORDER BY timestamp DESC")
        results_data = cursor.fetchall()
        cursor.execute(f"SELECT * FROM {FAMILIARITY_TABLE} ORDER BY timestamp DESC")
        familiarity_data = cursor.fetchall()
        print(f"Admin view: Fetched {len(results_data)} annotations, {len(familiarity_data)} familiarity ratings.")
    except MySQLError as err: print(f"Error fetching admin data: {err}"); flash('Error fetching results.', 'error')
    except Exception as e: print(f"Unexpected error fetching admin data: {e}"); flash('Unexpected error.', 'error')
    return render_template('admin.html', results=results_data, familiarity_ratings=familiarity_data)

@app.route('/admin/download_raw_annotations')
def download_raw_annotations():
    """Downloads the raw annotation data (results_cross table)."""
    # !! SECURITY WARNING: Add authentication !!
    print("Raw Annotations download request.")
    db_conn_raw = None
    try:
        db_conn_raw = mysql.connector.connect(
            host=app.config['MYSQL_HOST'], user=app.config['MYSQL_USER'],
            password=app.config['MYSQL_PASSWORD'], database=app.config['MYSQL_DB'],
            port=app.config['MYSQL_PORT']
        )
        if not db_conn_raw.is_connected(): raise MySQLError("Raw Download: Failed connection.")
        df = pd.read_sql_query(f"SELECT * FROM {RESULTS_TABLE_CROSS} ORDER BY timestamp DESC", db_conn_raw)
        if df.empty: flash("Annotations table ('{RESULTS_TABLE_CROSS}') is empty.", "warning"); return redirect(url_for('admin_view'))
        buffer = io.BytesIO()
        df.to_csv(buffer, index=False, encoding='utf-8')
        buffer.seek(0)
        return send_file(buffer, mimetype='text/csv', download_name='raw_cross_annotations.csv', as_attachment=True)
    except (MySQLError, pd.errors.DatabaseError) as e: print(f"DB/Pandas Error (Raw Annotations): {e}"); flash(f"Error fetching raw annotations: {e}", "error"); return redirect(url_for('admin_view'))
    except Exception as e: import traceback; print(f"Error (Raw Annotations):\n{traceback.format_exc()}"); flash(f"Error preparing raw annotations download: {e}", "error"); return redirect(url_for('admin_view'))
    finally:
        if db_conn_raw and db_conn_raw.is_connected(): db_conn_raw.close()

@app.route('/admin/download_familiarity')
def download_familiarity_ratings():
    """Downloads the familiarity ratings."""
    # !! SECURITY WARNING: Add authentication !!
    print("Familiarity Ratings download request.")
    db_conn_fam = None
    try:
        db_conn_fam = mysql.connector.connect(
            host=app.config['MYSQL_HOST'], user=app.config['MYSQL_USER'],
            password=app.config['MYSQL_PASSWORD'], database=app.config['MYSQL_DB'],
            port=app.config['MYSQL_PORT']
        )
        if not db_conn_fam.is_connected(): raise MySQLError("Familiarity Download: Failed connection.")
        df = pd.read_sql_query(f"SELECT * FROM {FAMILIARITY_TABLE} ORDER BY timestamp DESC", db_conn_fam)
        if df.empty: flash("Familiarity ratings table ('{FAMILIARITY_TABLE}') is empty.", "warning"); return redirect(url_for('admin_view'))
        buffer = io.BytesIO()
        df.to_csv(buffer, index=False, encoding='utf-8')
        buffer.seek(0)
        return send_file(buffer, mimetype='text/csv', download_name='familiarity_ratings.csv', as_attachment=True)
    except (MySQLError, pd.errors.DatabaseError) as e: print(f"DB/Pandas Error (Familiarity): {e}"); flash(f"Error fetching familiarity ratings: {e}", "error"); return redirect(url_for('admin_view'))
    except Exception as e: import traceback; print(f"Error (Familiarity):\n{traceback.format_exc()}"); flash(f"Error preparing familiarity download: {e}", "error"); return redirect(url_for('admin_view'))
    finally:
        if db_conn_fam and db_conn_fam.is_connected(): db_conn_fam.close()

# --- Main Execution ---
if __name__ == '__main__':
    print(f"Initializing database '{MYSQL_DB}' for Cross-State app...")
    with app.app_context(): # Use app context for init_db if it relies on g
        init_db()
    print("Starting Flask application (Cross-State Version)...")
    # Use a different port (e.g., 5001) to avoid conflict with the first app version
    app.run(debug=True, host='0.0.0.0', port=5001) # Set debug=False for production