# process_results_cross.py
# (Renamed file to match the cross-state project)

import mysql.connector
from mysql.connector import Error as MySQLError
import pandas as pd
import numpy as np
import os
import sys

# --- Configuration ---

# MySQL Connection Details for the CROSS-STATE Database
MYSQL_HOST = 'localhost'
MYSQL_USER = 'stereotype_user'
MYSQL_PASSWORD = 'RespAI@2025' # Your specified password
MYSQL_DB = 'stereotype_cross' # Connect to the SECOND project's DB
MYSQL_PORT = 3306

# Table Names in the 'stereotype_cross' database
RESULTS_TABLE = 'results_cross'
FAMILIARITY_TABLE = 'familiarity_ratings'

# Input/Output Files
STEREOTYPES_CSV = os.path.join('data', 'stereotypes.csv') # Definitions file
OUTPUT_CSV = 'final_aggregated_cross_stereotypes.csv' # Output file name

print(f"--- Starting Cross-State Data Processing (DB: {MYSQL_DB}) ---")

# --- Check Dependencies ---
# (Keep the dependency checks from the previous script)
try: import mysql.connector; import pandas as pd; import numpy as np
except ImportError as e: print(f"Error: Missing library ({e}). Please install requirements."); sys.exit(1)

# --- Helper Functions ---
def calculate_mean_offensiveness(series):
    """Calculates mean of non-negative offensiveness ratings."""
    valid_ratings = series[series >= 0]
    return valid_ratings.mean() if not valid_ratings.empty else np.nan

def calculate_mean_familiarity(series):
    """Calculates mean of non-negative familiarity ratings."""
    # Assuming familiarity is 0-5. Handle potential -1 if needed.
    valid_ratings = series[series >= 0]
    return valid_ratings.mean() if not valid_ratings.empty else np.nan

# --- Main Processing Logic ---
db_conn = None
try:
    # --- Step 1: Load Data ---
    base_dir = os.path.dirname(os.path.abspath(__file__))
    stereotypes_path = os.path.join(base_dir, STEREOTYPES_CSV)
    output_path = os.path.join(base_dir, OUTPUT_CSV)

    if not os.path.exists(stereotypes_path):
        raise FileNotFoundError(f"Stereotypes definition file not found: {stereotypes_path}")

    # Connect to the cross-state MySQL database
    print(f"Connecting to MySQL database '{MYSQL_DB}'...")
    try:
        db_conn = mysql.connector.connect(
            host=MYSQL_HOST, user=MYSQL_USER, password=MYSQL_PASSWORD,
            database=MYSQL_DB, port=MYSQL_PORT
        )
        if not db_conn.is_connected(): raise MySQLError("Failed to connect.")
        print("Connected to MySQL.")

        # Load ANNOTATION results from the 'results_cross' table
        results_df = pd.read_sql_query(f"SELECT * FROM {RESULTS_TABLE}", db_conn)
        print(f"Loaded {len(results_df)} rows from annotation table '{RESULTS_TABLE}'.")

        # Load FAMILIARITY ratings from the 'familiarity_ratings' table
        familiarity_df = pd.read_sql_query(f"SELECT * FROM {FAMILIARITY_TABLE}", db_conn)
        print(f"Loaded {len(familiarity_df)} rows from familiarity table '{FAMILIARITY_TABLE}'.")

    except MySQLError as e:
         print(f"\nMySQL Error loading data: {e}"); raise
    except Exception as e:
         print(f"\nError reading data using Pandas: {e}"); raise
    finally:
        if db_conn and db_conn.is_connected(): db_conn.close(); print("MySQL connection closed.")

    # Exit if no annotation data to process
    if results_df.empty:
        print("Annotation results table is empty. Nothing to process.")
        sys.exit(0)

    # Prepare Stereotype Definitions (same as before)
    print(f"Loading stereotype definitions from: {stereotypes_path}")
    stereotypes_df = pd.read_csv(stereotypes_path, encoding='utf-8-sig')
    stereotypes_df['Subsets_List'] = stereotypes_df['Subsets'].fillna('').astype(str).apply(
        lambda x: [s.strip() for s in x.split(',') if s.strip()]
    )
    subset_lookup = stereotypes_df.set_index(['State', 'Category', 'Superset'])['Subsets_List'].to_dict()
    print(f"Loaded {len(stereotypes_df)} stereotype definitions.")

    # --- Step 2: Calculate Average Familiarity per Target State ---
    print("Calculating average familiarity per target state...")
    if familiarity_df.empty:
        print("Warning: Familiarity ratings table is empty. Average Familiarity will be NaN.")
        # Create an empty structure to avoid merge errors later
        avg_familiarity = pd.DataFrame(columns=['Stereotype_State', 'Average_Familiarity'])
    else:
        # Group by the state the rating is ABOUT ('target_state')
        familiarity_grouped = familiarity_df.groupby('target_state')
        # Calculate the mean familiarity, using the helper function
        avg_familiarity = familiarity_grouped.agg(
            Average_Familiarity=('familiarity_rating', calculate_mean_familiarity)
        ).reset_index()
        # Rename 'target_state' to 'Stereotype_State' to match the results data for merging
        avg_familiarity = avg_familiarity.rename(columns={'target_state': 'Stereotype_State'})
        print(f"Calculated average familiarity for {len(avg_familiarity)} states.")
        # print(avg_familiarity.head()) # Optional: print first few rows


    # --- Step 3: Expand Annotations ---
    print("Expanding annotations to include subsets...")
    # Use the 'target_state' column from results_df as the state the stereotype is ABOUT
    results_df['Stereotype_State'] = results_df['target_state'] # Define the key state column

    expanded_rows = []
    for index, result_row in results_df.iterrows():
        stereotype_state = result_row['Stereotype_State'] # State stereotype is ABOUT
        category = result_row['category']
        superset = result_row['attribute_superset']
        annotation = result_row['annotation']
        rating = result_row['offensiveness_rating']
        # Include user's native state if needed for context later (optional)
        # native_state = result_row['native_state']

        # Add Superset row
        expanded_rows.append({
            'Stereotype_State': stereotype_state, 'Category': category, 'Attribute': superset,
            'annotation': annotation, 'offensiveness_rating': rating
        })
        # Add Subset rows
        lookup_key = (stereotype_state, category, superset)
        subsets_list = subset_lookup.get(lookup_key, [])
        for subset in subsets_list:
            expanded_rows.append({
                'Stereotype_State': stereotype_state, 'Category': category, 'Attribute': subset,
                'annotation': annotation, 'offensiveness_rating': rating
            })

    if not expanded_rows:
        print("Warning: No annotations could be expanded.")
        expanded_annotations_df = pd.DataFrame(columns=['Stereotype_State', 'Category', 'Attribute', 'annotation', 'offensiveness_rating'])
    else:
        expanded_annotations_df = pd.DataFrame(expanded_rows)
    print(f"Created {len(expanded_annotations_df)} expanded annotation rows.")

    # --- Step 4: Aggregate Annotation Data ---
    print("Aggregating expanded annotation results...")
    if expanded_annotations_df.empty:
        print("Skipping annotation aggregation as there are no expanded annotations.")
        aggregated_annotations = pd.DataFrame(columns=['Stereotype_State', 'Category', 'Attribute', 'Stereotype_Votes', 'Not_Stereotype_Votes', 'Not_Sure_Votes', 'Average_Offensiveness'])
    else:
        # Group by the State the stereotype is about, its Category, and the Attribute
        grouped = expanded_annotations_df.groupby(['Stereotype_State', 'Category', 'Attribute'])
        aggregated_annotations = grouped.agg(
            Stereotype_Votes=('annotation', lambda x: (x == 'Stereotype').sum()),
            Not_Stereotype_Votes=('annotation', lambda x: (x == 'Not a Stereotype').sum()),
            Not_Sure_Votes=('annotation', lambda x: (x == 'Not sure').sum()),
            Average_Offensiveness=('offensiveness_rating', calculate_mean_offensiveness)
        ).reset_index()
        aggregated_annotations['Average_Offensiveness'] = aggregated_annotations['Average_Offensiveness'].round(2)
        print(f"Annotation aggregation complete. Result has {len(aggregated_annotations)} rows.")

    # --- Step 5: Merge Average Familiarity with Aggregated Annotations ---
    print("Merging average familiarity ratings with aggregated results...")
    # Use a left merge to keep all aggregated stereotype rows
    # Merge on 'Stereotype_State' (which corresponds to 'target_state' in familiarity data)
    final_aggregated_data = pd.merge(
        aggregated_annotations,
        avg_familiarity,
        on='Stereotype_State',
        how='left' # Keep all rows from aggregated_annotations
    )
    # Rename the new column for clarity
    final_aggregated_data = final_aggregated_data.rename(columns={'Average_Familiarity': 'Avg_Familiarity_Rating'})
    final_aggregated_data['Avg_Familiarity_Rating'] = final_aggregated_data['Avg_Familiarity_Rating'].round(2)

    # Reorder columns for better readability (optional)
    desired_cols = ['Stereotype_State', 'Category', 'Attribute',
                    'Stereotype_Votes', 'Not_Stereotype_Votes', 'Not_Sure_Votes',
                    'Avg_Familiarity_Rating', 'Average_Offensiveness']
    # Ensure all desired columns exist before reordering
    final_columns = [col for col in desired_cols if col in final_aggregated_data.columns]
    final_aggregated_data = final_aggregated_data[final_columns]


    print(f"Merging complete. Final result has {len(final_aggregated_data)} rows.")

    # --- Step 6: Save Output ---
    print(f"Saving final aggregated data to: {output_path}")
    try:
        final_aggregated_data.to_csv(output_path, index=False, encoding='utf-8')
        print(f"Successfully saved aggregated results to {OUTPUT_CSV}")
    except Exception as e:
        print(f"\nError saving output file '{output_path}': {e}"); raise

    print(f"--- Cross-State Data Processing Finished Successfully ---")

# --- Error Handling ---
except FileNotFoundError as e: print(f"\nProcessing Error: {e}"); sys.exit(1)
except pd.errors.EmptyDataError as e: print(f"\nProcessing Error: {e}. Input file empty?"); sys.exit(1)
except KeyError as e: print(f"\nProcessing Error: Missing column: {e}. Check DB/CSV structure."); sys.exit(1)
except Exception as e: import traceback; print(f"\nUnexpected processing error:\n{traceback.format_exc()}"); sys.exit(1)