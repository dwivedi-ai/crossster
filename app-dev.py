# stereotype_quiz_app/app_cross_state.py
# Version 2: Cross-State Stereotype Annotation Quiz (Fixed)

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
import traceback # For detailed error logging

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
            g.cursor = g.db.cursor(dictionary=True) # Use dictionary cursor for easier access
        except MySQLError as err:
            print(f"FATAL: Error connecting to MySQL: {err}")
            flash('Database connection error. Please contact admin.', 'error')
            g.db = None; g.cursor = None # Ensure g attributes are cleared on error
    # Ensure cursor is returned even if connection existed but cursor was somehow removed
    return getattr(g, 'cursor', None)


@app.teardown_appcontext
def close_db(error):
    """Closes the database cursor and connection at the end of the request."""
    cursor = g.pop('cursor', None)
    if cursor: cursor.close()
    db = g.pop('db', None)
    # Ensure db is valid and connected before trying to close
    if db and hasattr(db, 'is_connected') and db.is_connected(): db.close()
    if error: print(f"App context teardown error: {error}")

def init_db():
    """Initializes the NEW database schema (stereotype_cross) if tables are missing."""
    temp_conn = None; temp_cursor = None
    print(f"Checking database '{app.config['MYSQL_DB']}' setup...")
    try:
        # Attempt connection first to create DB if not exists (though usually handled by MySQL setup)
        try:
             temp_conn = mysql.connector.connect(
                host=app.config['MYSQL_HOST'],
                user=app.config['MYSQL_USER'],
                password=app.config['MYSQL_PASSWORD'],
                port=app.config['MYSQL_PORT']
            )
             temp_cursor = temp_conn.cursor()
             temp_cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{app.config['MYSQL_DB']}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
             print(f"Database '{app.config['MYSQL_DB']}' ensured.")
             temp_cursor.close()
             temp_conn.close()
        except MySQLError as db_err:
             print(f"Warning: Could not ensure database exists (might require manual creation or permissions): {db_err}")
             # Continue assuming DB exists if connection fails here

        # Connect specifically to the target DB for schema execution
        temp_conn = mysql.connector.connect(
            host=app.config['MYSQL_HOST'],
            user=app.config['MYSQL_USER'],
            password=app.config['MYSQL_PASSWORD'],
            database=app.config['MYSQL_DB'], # Connect to the specific DB
            port=app.config['MYSQL_PORT']
        )
        temp_cursor = temp_conn.cursor()

        base_dir = os.path.dirname(os.path.abspath(__file__))
        schema_path = os.path.join(base_dir, SCHEMA_FILE)

        try:
            with open(schema_path, mode='r', encoding='utf-8') as f:
                sql_script = f.read()

            # Split the script into individual statements based on semicolon, handling comments
            sql_statements = [statement.strip() for statement in sql_script.split(';') if statement.strip() and not statement.strip().startswith('--')]

            if not sql_statements:
                print(f"Warning: No executable SQL statements found in {schema_path}")
            else:
                print(f"Executing {len(sql_statements)} statements from schema...")
                for statement in sql_statements:
                    try:
                        # print(f"Executing: {statement[:100]}...") # Optional: Print start of statement
                        temp_cursor.execute(statement)
                    except MySQLError as stmt_err:
                        # Handle expected errors like "Table already exists" gracefully with IF NOT EXISTS
                        # Print other warnings/errors but continue if possible
                        print(f"Warning/Error executing statement (might be ok if using 'IF NOT EXISTS'): {stmt_err}")
                        # Raise the error to stop the whole process if a statement is critical and fails:
                        # if "syntax error" in str(stmt_err): raise stmt_err

            temp_conn.commit() # Commit after all statements are executed successfully
            print(f"Database tables from '{SCHEMA_FILE}' created/verified successfully in '{app.config['MYSQL_DB']}'.")
        except FileNotFoundError:
            print(f"FATAL ERROR: Schema file '{schema_path}' not found.")
            raise # Re-raise to stop the app if schema is critical
        except MySQLError as err:
            print(f"FATAL ERROR executing schema file '{SCHEMA_FILE}': {err}")
            if temp_conn and temp_conn.is_connected(): temp_conn.rollback() # Rollback any partial changes
            raise # Re-raise
        except Exception as e:
            print(f"FATAL: Unexpected error initializing schema from file: {e}")
            if temp_conn and temp_conn.is_connected(): temp_conn.rollback()
            raise # Re-raise
    except MySQLError as conn_err:
        # Error connecting to the specific database
        print(f"FATAL: Error connecting to database '{app.config['MYSQL_DB']}' during init: {conn_err}")
        raise # Re-raise essential connection errors
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
        with open(full_filepath, mode='r', encoding='utf-8-sig') as infile: # Use utf-8-sig to handle potential BOM
            reader = csv.DictReader(infile)
            required_cols = ['State', 'Category', 'Superset', 'Subsets']
            # Check if reader.fieldnames is None or empty before checking columns
            if not reader.fieldnames or not all(field in reader.fieldnames for field in required_cols):
                 missing = [c for c in required_cols if c not in (reader.fieldnames or [])]
                 raise ValueError(f"CSV missing required columns: {missing}. Found columns: {reader.fieldnames}")

            for i, row in enumerate(reader):
                try:
                    # Use .get with default empty string and strip whitespace
                    state = row.get('State','').strip()
                    category = row.get('Category','Uncategorized').strip()
                    superset = row.get('Superset','').strip()
                    subsets_str = row.get('Subsets','') # Default to empty string if missing

                    # Basic validation: Ensure essential fields are not empty
                    if not state or not superset:
                        print(f"Warning: Skipping CSV row {i+1} due to missing State or Superset. Row: {row}")
                        continue

                    # Process subsets: split, strip, filter empty, sort
                    subsets = sorted([s.strip() for s in subsets_str.split(',') if s.strip()])

                    stereotype_data.append({
                        'state': state,
                        'category': category if category else 'Uncategorized', # Ensure category has a value
                        'superset': superset,
                        'subsets': subsets
                        })
                except Exception as row_err:
                    print(f"Error processing CSV row {i+1}: {row_err}. Row data: {row}");
                    continue # Skip problematic row

        print(f"Successfully loaded {len(stereotype_data)} stereotype entries from {full_filepath}")
        # Optional: Print first few entries for verification
        # if stereotype_data: print(f"First entry: {stereotype_data[0]}")
        return stereotype_data
    except FileNotFoundError:
        print(f"FATAL ERROR: CSV file not found at {full_filepath}. App may not function correctly.");
        return [] # Return empty list to prevent crash, but log error
    except ValueError as ve:
        print(f"FATAL ERROR processing CSV structure: {ve}");
        return []
    except Exception as e:
        print(f"FATAL ERROR loading data: {e}\n{traceback.format_exc()}");
        return []

# --- Load Data & Get List of States ---
ALL_STEREOTYPE_DATA = load_stereotype_data()
ALL_DEFINED_STATES = sorted(list(set(item['state'] for item in ALL_STEREOTYPE_DATA)))
if not ALL_STEREOTYPE_DATA or not ALL_DEFINED_STATES:
    print("\nCRITICAL ERROR: Stereotype data loading failed or no states found! App cannot function.\n")
    # Provide defaults to prevent immediate crashes in templates, but the app is non-functional
    ALL_STEREOTYPE_DATA = []
    ALL_DEFINED_STATES = ["Error: Check Logs"]
print(f"States available for selection/annotation: {ALL_DEFINED_STATES if 'Error' not in ALL_DEFINED_STATES[0] else 'LOADING FAILED'}")


# --- Flask Routes ---

@app.route('/', methods=['GET', 'POST'])
def index():
    """Handles the initial user info form page for cross-state annotation."""
    if request.method == 'POST':
        user_name = request.form.get('name', '').strip()
        native_state = request.form.get('native_state')
        user_age_str = request.form.get('age')
        user_sex = request.form.get('sex') # Will be 'Male' or 'Female' or None if not selected

        errors = False
        if not user_name: flash('Name is required.', 'error'); errors = True
        if not native_state or native_state not in ALL_DEFINED_STATES:
            flash('Please select your valid native state.', 'error'); errors = True
        # Check if sex was selected - it's not mandatory per schema (NULL allowed) but might be desired
        if not user_sex:
             flash('Please select your sex.', 'error'); errors = True # Keep if mandatory for study

        user_age = None
        if user_age_str:
            try:
                user_age = int(user_age_str)
                if user_age <= 0 or user_age > 120: # Basic sanity check
                     flash('Please enter a realistic age.', 'error'); errors = True
            except ValueError:
                 flash('Please enter a valid number for age.', 'error'); errors = True
        # else: user_age remains None, which is allowed by schema

        if errors: return render_template('index.html', states=ALL_DEFINED_STATES, form_data=request.form)

        # --- Setup Session for the Quiz ---
        session.clear()
        session['user_name'] = user_name
        session['native_state'] = native_state
        session['user_age'] = user_age # Can be None
        session['user_sex'] = user_sex # Can be None

        # Ensure ALL_DEFINED_STATES did not fail loading
        if "Error: Check Logs" in ALL_DEFINED_STATES:
             flash("Error loading state data. Cannot start quiz. Please contact admin.", 'error')
             return render_template('index.html', states=ALL_DEFINED_STATES, form_data=request.form)

        target_states = [s for s in ALL_DEFINED_STATES if s != native_state]
        if not target_states:
            flash("You are from the only state defined, or no other states available. Thank you!", 'info')
            # Redirect to thank you or a specific message page
            return redirect(url_for('thank_you'))

        random.shuffle(target_states)
        session['target_states'] = target_states
        session['current_state_index'] = 0

        print(f"User '{user_name}' (Native: {native_state}, Age: {user_age}, Sex: {user_sex}) starting quiz. Target states ({len(target_states)}): {target_states}")
        return redirect(url_for('quiz_cross')) # Redirect to the quiz route

    # GET request
    session.clear() # Clear session on fresh visit to index
    return render_template('index.html', states=ALL_DEFINED_STATES, form_data={})


@app.route('/quiz', methods=['GET', 'POST'])
def quiz_cross():
    """Handles the sequential display and submission for each target state."""

    # --- Validate Session ---
    required_session_keys = ['user_name', 'native_state', 'target_states', 'current_state_index']
    if not all(key in session for key in required_session_keys):
        flash('Your session has expired or is invalid. Please start again.', 'warning')
        # Log this potentially?
        print(f"Warning: Invalid session state access attempt. Missing keys: {[k for k in required_session_keys if k not in session]}")
        return redirect(url_for('index'))

    target_states = session['target_states']
    current_index = session['current_state_index']

    # --- Check if Quiz is Complete ---
    if current_index >= len(target_states):
        print(f"User '{session.get('user_name', 'Unknown')}' finished all states.")
        return redirect(url_for('thank_you')) # Go to thank you page

    # Current target state based on index stored in session
    current_target_state = target_states[current_index]

    # --- Handle POST Request (Saving data for the state just completed) ---
    if request.method == 'POST':
        print(f"POST received for state index {current_index} ({current_target_state}) by user '{session.get('user_name')}'")
        cursor = get_db()
        if not cursor:
             flash('Database connection failed. Cannot save progress.', 'error')
             # Redirect back to GET for the same state, data won't be saved.
             return redirect(url_for('quiz_cross'))

        db_connection = g.db # Use the connection from g for transaction control

        try:
            # --- Retrieve & Validate Familiarity Rating ---
            familiarity_rating_str = request.form.get('familiarity_rating')
            if familiarity_rating_str is None:
                 # This should ideally be caught by client-side validation (required field)
                 flash('Error: Familiarity rating was not submitted. Please select a rating.', 'error')
                 # No db changes made yet, so no rollback needed, just redirect
                 print(f"Error: Familiarity rating missing in POST for {current_target_state}.")
                 # Stay on the same page
                 return redirect(url_for('quiz_cross'))

            try:
                familiarity_rating = int(familiarity_rating_str)
                if not (0 <= familiarity_rating <= 5): raise ValueError("Rating out of range")
            except (ValueError, TypeError):
                flash('Invalid familiarity rating submitted. Please select a value between 0 and 5.', 'error')
                print(f"Invalid familiarity rating received: '{familiarity_rating_str}' for {current_target_state}")
                # No db changes made yet
                return redirect(url_for('quiz_cross')) # Stay on same page

            # --- Start Transaction Explicitly (though autocommit=False handles it implicitly) ---
            # cursor.execute("START TRANSACTION;") # Generally not needed with autocommit=False

            # --- Save Familiarity Rating ---
            fam_sql = f"""
                INSERT INTO {FAMILIARITY_TABLE}
                (native_state, target_state, familiarity_rating, user_name, user_age, user_sex)
                VALUES (%(native_state)s, %(target_state)s, %(rating)s, %(name)s, %(age)s, %(sex)s)
            """
            fam_data = {
                'native_state': session['native_state'],
                'target_state': current_target_state,
                'rating': familiarity_rating,
                'name': session['user_name'],
                'age': session.get('user_age'), # Get potentially None value
                'sex': session.get('user_sex')  # Get potentially None value
            }
            cursor.execute(fam_sql, fam_data)
            print(f"Executed INSERT for familiarity rating ({familiarity_rating}) for {current_target_state}")

            # --- Save Stereotype Annotations ---
            annotations_to_insert = []
            # Get the number of items PRESENTED on the previous page
            # CRITICAL FIX: Ensure 'num_quiz_items' is correctly retrieved from the hidden input
            num_items_on_page_str = request.form.get('num_quiz_items')
            if num_items_on_page_str is None:
                 # This indicates the hidden field is missing or misnamed in the HTML form
                 print(f"CRITICAL ERROR: Hidden input 'num_quiz_items' not found in form submission for state {current_target_state}.")
                 flash("A form processing error occurred (missing item count). Please try again.", 'error')
                 db_connection.rollback() # Rollback the familiarity rating insert
                 return redirect(url_for('quiz_cross')) # Stay on same page

            try:
                 num_items_on_page = int(num_items_on_page_str)
            except ValueError:
                 print(f"CRITICAL ERROR: Invalid value received for 'num_quiz_items': '{num_items_on_page_str}'")
                 flash("A form processing error occurred (invalid item count). Please try again.", 'error')
                 db_connection.rollback() # Rollback the familiarity rating insert
                 return redirect(url_for('quiz_cross')) # Stay on same page


            # --- DEBUG PRINT ---
            # print(f"--- Processing State: {current_target_state} ---")
            # print(f"Received num_quiz_items from form: {num_items_on_page}")
            # --- END DEBUG ---

            for i in range(num_items_on_page): # Iterate based on items presented
                identifier = str(i) # Index used in the template loop

                # Retrieve data for this specific item
                superset = request.form.get(f'superset_{identifier}')
                category = request.form.get(f'category_{identifier}')
                annotation = request.form.get(f'annotation_{identifier}')
                # Retrieve offensiveness rating string, even if annotation wasn't 'Stereotype' initially
                rating_str = request.form.get(f'offensiveness_{identifier}')

                # --- DEBUG PRINT ---
                # print(f"Item {i}: Superset='{superset}', Category='{category}', Annotation='{annotation}', OffensivenessStr='{rating_str}'")
                # --- END DEBUG ---

                # Basic validation: Ensure core annotation data isn't missing
                # Client-side validation should prevent this, but double-check
                if not annotation or not superset or not category:
                     print(f"Warning: Missing core data (annotation/superset/category) for item index {identifier} on state {current_target_state}. Skipping DB insert for this item. Data: A='{annotation}', S='{superset}', C='{category}'")
                     # Decide whether to:
                     # 1. Skip this item (current behavior)
                     # continue
                     # 2. Halt the entire submission (might be safer if data integrity is paramount)
                     flash(f"Incomplete data received for one of the items for {current_target_state}. Submission cancelled.", 'error')
                     db_connection.rollback()
                     return redirect(url_for('quiz_cross')) # Go back to the same page

                # Process Offensiveness Rating only if annotation is 'Stereotype'
                offensiveness = -1 # Default value as per schema
                if annotation == 'Stereotype':
                    # Check if rating is present AND valid (client validation should ensure presence)
                    if rating_str is not None:
                        try:
                            offensiveness = int(rating_str)
                            # Ensure rating is within the valid range (0-5)
                            if not (0 <= offensiveness <= 5):
                                print(f"Warning: Invalid offensiveness rating value ({offensiveness}) for item index {identifier}. Defaulting to -1.")
                                offensiveness = -1 # Reset to default if out of range
                        except (ValueError, TypeError):
                             print(f"Warning: Non-integer offensiveness rating ('{rating_str}') for item index {identifier}. Defaulting to -1.")
                             offensiveness = -1 # Reset to default if conversion fails
                    else:
                        # This case implies 'Stereotype' was selected, but no rating was submitted
                        # This *should* be blocked by client-side validation if working correctly
                        print(f"ERROR: Offensiveness rating missing for Stereotype item index {identifier} despite client validation. Defaulting to -1.")
                        offensiveness = -1 # Store default, but log as an error


                # Append data dictionary for this annotation to the list for executemany
                annotations_to_insert.append({
                    'native_state': session['native_state'],
                    'target_state': current_target_state,
                    'user_name': session['user_name'],
                    'user_age': session.get('user_age'), # Handles None
                    'user_sex': session.get('user_sex'), # Handles None
                    'category': category,
                    'attribute_superset': superset,
                    'annotation': annotation,
                    'offensiveness_rating': offensiveness
                })
            # End loop through quiz items

            # --- DEBUG PRINT ---
            # print(f"Prepared annotations_to_insert (Count: {len(annotations_to_insert)}):")
            # If needed print the list: print(annotations_to_insert)
            # --- END DEBUG ---

            # --- Save Annotations if any were successfully processed ---
            if annotations_to_insert:
                # Ensure the list size matches the expected number of items if validation is strict
                if len(annotations_to_insert) != num_items_on_page:
                     print(f"Warning: Number of annotations to insert ({len(annotations_to_insert)}) does not match number of items on page ({num_items_on_page}). This might indicate skipped items due to errors.")
                     # Decide if this discrepancy warrants a rollback or just a warning

                results_sql = f"""
                    INSERT INTO {RESULTS_TABLE_CROSS}
                    (native_state, target_state, user_name, user_age, user_sex, category, attribute_superset, annotation, offensiveness_rating)
                    VALUES (%(native_state)s, %(target_state)s, %(user_name)s, %(user_age)s, %(user_sex)s, %(category)s, %(attribute_superset)s, %(annotation)s, %(offensiveness_rating)s)
                """
                try:
                    # --- DEBUG PRINT ---
                    # print(f"Attempting cursor.executemany with {len(annotations_to_insert)} records...")
                    # --- END DEBUG ---
                    cursor.executemany(results_sql, annotations_to_insert)
                    print(f"Executed INSERT for {len(annotations_to_insert)} annotations for {current_target_state}")
                except MySQLError as exec_many_err:
                    # Handle potential errors during the batch insert specifically
                    print(f"DB Error during executemany for annotations (State: {current_target_state}): {exec_many_err}")
                    # Add more details if possible (e.g., check error code)
                    print(f"Data attempted (first record): {annotations_to_insert[0] if annotations_to_insert else 'N/A'}")
                    flash("Database error saving your detailed responses. Please try again.", 'error');
                    db_connection.rollback() # Rollback everything for this state
                    return redirect(url_for('quiz_cross')) # Stay on the same page

            elif num_items_on_page > 0: # If there were items but list is empty, it means all failed validation
                 print(f"Warning: No annotations were saved for state {current_target_state} because all items failed validation or were skipped.")
                 # Depending on requirements, maybe rollback familiarity too if no annotations saved?
                 # flash("Could not save any annotations for this state due to data issues.", 'warning')
                 # db_connection.rollback() # Optional: Rollback everything if annotations are critical
                 # return redirect(url_for('quiz_cross'))
                 # Or just proceed, committing only the familiarity rating (current logic path)
                 print("Proceeding to commit familiarity rating only.")

            else: # num_items_on_page was 0, so nothing to insert
                 print(f"No quiz items were presented for state {current_target_state}, skipping annotation insert.")


            # --- Commit Transaction ---
            # If we reached here without errors causing a return/redirect, commit the transaction
            db_connection.commit()
            print(f"Committed transaction successfully for state {current_target_state}")

            # --- Advance to Next State ---
            session['current_state_index'] = current_index + 1
            session.modified = True # Explicitly mark session as modified
            print(f"Advanced user '{session.get('user_name')}' to state index {session['current_state_index']}")
            return redirect(url_for('quiz_cross'))

        except MySQLError as db_err:
             # Catch errors from the initial familiarity insert or commit
             print(f"DB Error during transaction for state {current_target_state}: {db_err}");
             print(traceback.format_exc()) # Print stack trace for DB errors
             try:
                 if db_connection and db_connection.is_connected(): db_connection.rollback()
                 print("Transaction rolled back due to DB error.")
             except Exception as rb_err:
                 print(f"Rollback failed after DB error: {rb_err}")
             flash("Database error saving responses. Your progress for this state was not saved. Please try again.", 'error');
             # Redirect back to GET for the *same* state to allow retry
             return redirect(url_for('quiz_cross'))

        except Exception as e:
             # Catch any other unexpected Python errors
             print(f"Unexpected Error processing POST for state {current_target_state}: {e}");
             print(traceback.format_exc()); # Print full stack trace
             try:
                 if db_connection and db_connection.is_connected(): db_connection.rollback()
                 print("Transaction rolled back due to unexpected error.")
             except Exception as rb_err:
                 print(f"Rollback failed after unexpected error: {rb_err}")
             flash("An unexpected error occurred processing your submission. Please restart the quiz.", 'error');
             # Consider redirecting to index on completely unexpected errors
             return redirect(url_for('index'))


    # --- Handle GET Request (Display current state's questions) ---
    print(f"GET request for state index {current_index} ({current_target_state}) by user '{session.get('user_name')}'")

    # Filter ALL data to get only items for the current target state
    quiz_items_for_state = [item for item in ALL_STEREOTYPE_DATA if item.get('state') == current_target_state]
    # Sort items maybe? By category then superset?
    quiz_items_for_state.sort(key=lambda x: (x.get('category', ''), x.get('superset', '')))

    is_last_state = (current_index == len(target_states) - 1)
    num_items_to_display = len(quiz_items_for_state)

    print(f"Rendering quiz page for {current_target_state} with {num_items_to_display} items. Is last state: {is_last_state}")

    return render_template('quiz.html',
                           target_state=current_target_state,
                           quiz_items=quiz_items_for_state,
                           user_info=session, # Pass session data for context (e.g., display name)
                           current_index=current_index,
                           total_states=len(target_states),
                           is_last_state=is_last_state,
                           num_quiz_items=num_items_to_display) # Pass the correct count


@app.route('/thank_you')
def thank_you():
    """Displays the thank you page."""
    user_name = session.get('user_name', 'Participant')
    print(f"Displaying thank you page for user '{user_name}'.")
    # Optionally clear session here if the quiz is truly over
    # session.clear()
    return render_template('thank_you.html', user_name=user_name)


# --- Admin Routes (Keep existing structure) ---
# !! Add proper authentication/authorization to admin routes in production !!
@app.route('/admin')
def admin_view():
    """Displays raw annotation results and familiarity ratings."""
    # AUTH CHECK HERE (e.g., check session for admin flag, use Flask-Login, etc.)
    print("Admin view accessed.")
    cursor = get_db()
    if not cursor: return redirect(url_for('index')) # Redirect if DB connection fails

    results_data = []; familiarity_data = [] # Initialize
    try:
        # Fetch annotations
        cursor.execute(f"SELECT * FROM {RESULTS_TABLE_CROSS} ORDER BY timestamp DESC, id DESC")
        results_data = cursor.fetchall() # fetchall() returns list of dicts due to dictionary=True cursor

        # Fetch familiarity ratings
        cursor.execute(f"SELECT * FROM {FAMILIARITY_TABLE} ORDER BY timestamp DESC, id DESC")
        familiarity_data = cursor.fetchall()

        print(f"Admin view: Fetched {len(results_data)} annotations, {len(familiarity_data)} familiarity ratings.")
    except MySQLError as err:
        print(f"Error fetching admin data: {err}");
        flash('Error fetching results from database.', 'error')
    except Exception as e:
         print(f"Unexpected error fetching admin data: {e}\n{traceback.format_exc()}");
         flash('An unexpected error occurred while fetching results.', 'error')

    # Pass fetched data (even if empty) to the template
    return render_template('admin.html', results=results_data, familiarity_ratings=familiarity_data)

@app.route('/admin/download_raw_annotations')
def download_raw_annotations():
    """Downloads the raw annotation data (results_cross table) as CSV."""
    # AUTH CHECK HERE
    print("Raw Annotations download request.")
    db_conn_raw = None # Use separate connection for safety with pandas
    try:
        # Establish a new connection for the download process
        db_conn_raw = mysql.connector.connect(
            host=app.config['MYSQL_HOST'], user=app.config['MYSQL_USER'],
            password=app.config['MYSQL_PASSWORD'], database=app.config['MYSQL_DB'],
            port=app.config['MYSQL_PORT']
        )
        if not db_conn_raw.is_connected(): raise MySQLError("Raw Download: Failed to establish DB connection.")

        # Use pandas to read data directly into a DataFrame
        query = f"SELECT * FROM {RESULTS_TABLE_CROSS} ORDER BY timestamp DESC, id DESC"
        df = pd.read_sql_query(query, db_conn_raw)

        if df.empty:
            flash(f"Annotations table ('{RESULTS_TABLE_CROSS}') is currently empty. No data to download.", "warning")
            return redirect(url_for('admin_view'))

        # Create an in-memory buffer for the CSV data
        buffer = io.BytesIO()
        df.to_csv(buffer, index=False, encoding='utf-8-sig') # Use utf-8-sig for Excel compatibility
        buffer.seek(0) # Rewind buffer to the beginning

        print(f"Prepared CSV download for {len(df)} annotations.")
        # Send the buffer as a file download
        return send_file(
            buffer,
            mimetype='text/csv',
            download_name='raw_cross_annotations.csv',
            as_attachment=True
        )
    except (MySQLError, pd.errors.DatabaseError) as db_pd_err:
        print(f"DB/Pandas Error during Raw Annotations download: {db_pd_err}");
        flash(f"Error fetching raw annotations from database: {db_pd_err}", "error")
        return redirect(url_for('admin_view'))
    except Exception as e:
        print(f"Unexpected Error during Raw Annotations download:\n{traceback.format_exc()}");
        flash(f"An unexpected error occurred preparing the raw annotations download: {e}", "error")
        return redirect(url_for('admin_view'))
    finally:
        # Ensure the separate connection is closed
        if db_conn_raw and db_conn_raw.is_connected():
            db_conn_raw.close()
            print("Raw download DB connection closed.")

@app.route('/admin/download_familiarity')
def download_familiarity_ratings():
    """Downloads the familiarity ratings (familiarity_ratings table) as CSV."""
    # AUTH CHECK HERE
    print("Familiarity Ratings download request.")
    db_conn_fam = None # Use separate connection
    try:
        db_conn_fam = mysql.connector.connect(
            host=app.config['MYSQL_HOST'], user=app.config['MYSQL_USER'],
            password=app.config['MYSQL_PASSWORD'], database=app.config['MYSQL_DB'],
            port=app.config['MYSQL_PORT']
        )
        if not db_conn_fam.is_connected(): raise MySQLError("Familiarity Download: Failed to establish DB connection.")

        query = f"SELECT * FROM {FAMILIARITY_TABLE} ORDER BY timestamp DESC, id DESC"
        df = pd.read_sql_query(query, db_conn_fam)

        if df.empty:
            flash(f"Familiarity ratings table ('{FAMILIARITY_TABLE}') is currently empty. No data to download.", "warning")
            return redirect(url_for('admin_view'))

        buffer = io.BytesIO()
        df.to_csv(buffer, index=False, encoding='utf-8-sig')
        buffer.seek(0)

        print(f"Prepared CSV download for {len(df)} familiarity ratings.")
        return send_file(
            buffer,
            mimetype='text/csv',
            download_name='familiarity_ratings.csv',
            as_attachment=True
        )
    except (MySQLError, pd.errors.DatabaseError) as db_pd_err:
        print(f"DB/Pandas Error during Familiarity Ratings download: {db_pd_err}");
        flash(f"Error fetching familiarity ratings from database: {db_pd_err}", "error")
        return redirect(url_for('admin_view'))
    except Exception as e:
        print(f"Unexpected Error during Familiarity Ratings download:\n{traceback.format_exc()}");
        flash(f"An unexpected error occurred preparing the familiarity ratings download: {e}", "error")
        return redirect(url_for('admin_view'))
    finally:
        if db_conn_fam and db_conn_fam.is_connected():
            db_conn_fam.close()
            print("Familiarity download DB connection closed.")


# --- Main Execution ---
if __name__ == '__main__':
    print(f"----- Stereotype Cross-State Quiz App Starting -----")
    print(f"Attempting to initialize database '{MYSQL_DB}'...")
    try:
        # Use app context for init_db as it might access app config or g
        with app.app_context():
            init_db()
        print(f"Database initialization completed for '{MYSQL_DB}'.")
    except Exception as init_err:
        print(f"FATAL: Database initialization failed: {init_err}")
        print("--- APPLICATION HALTED ---")
        # Exit if DB init fails, as the app likely can't run
        exit(1) # Use a non-zero exit code to indicate failure

    print("Starting Flask application (Cross-State Version)...")
    # Run on a specific port (e.g., 5001) and accessible externally (0.0.0.0)
    # Set debug=False for production environments
    app.run(debug=True, host='0.0.0.0', port=5001)
    print("----- Stereotype Cross-State Quiz App Stopped -----")