# preprocess_csv.py
import csv
import os

INPUT_CSV_FILENAME = 'data/dataset.csv'
OUTPUT_CSV_FILENAME = 'stereotypes.csv' # The new, corrected file
REQUIRED_COLS = ['State', 'Category', 'Superset', 'Subsets'] # Minimum expected base columns
SUBSET_START_COL = 'Subsets' # The name of the first column containing subsets

print(f"Starting preprocessing of '{INPUT_CSV_FILENAME}'...")

try:
    # Ensure input file exists
    if not os.path.exists(INPUT_CSV_FILENAME):
        raise FileNotFoundError(f"Input file '{INPUT_CSV_FILENAME}' not found in the current directory.")

    processed_rows = 0
    # Use 'with' statements for automatic file closing
    with open(INPUT_CSV_FILENAME, mode='r', encoding='utf-8', newline='') as infile, \
         open(OUTPUT_CSV_FILENAME, mode='w', encoding='utf-8', newline='') as outfile:

        reader = csv.reader(infile) # Use standard reader to handle variable columns easily

        # --- Read and Validate Header ---
        try:
            header = next(reader) # Read the first row as header
        except StopIteration:
            raise ValueError(f"CSV file '{INPUT_CSV_FILENAME}' appears to be empty.")

        print(f"Input CSV header found: {header}")

        # Find indices of required columns and the start of subsets
        try:
            state_idx = header.index('State')
            category_idx = header.index('Category')
            superset_idx = header.index('Superset')
            subset_start_idx = header.index(SUBSET_START_COL)
        except ValueError as e:
            raise ValueError(f"Missing required column in header: {e}. Expected {REQUIRED_COLS}")

        # Define the header for the output file
        output_header = ['State', 'Category', 'Superset', 'Subsets']
        writer = csv.writer(outfile)
        writer.writerow(output_header) # Write the new header
        print(f"Writing consolidated data to '{OUTPUT_CSV_FILENAME}' with header: {output_header}")

        # --- Process Data Rows ---
        for i, row in enumerate(reader):
            current_row_num = i + 2 # +1 for 1-based index, +1 for header row

            # Basic check for row length consistency (optional but good)
            if len(row) < subset_start_idx + 1:
                 print(f"Warning: Skipping row {current_row_num}. Row has fewer columns ({len(row)}) than expected subset start index ({subset_start_idx}). Row data: {row}")
                 continue

            state = row[state_idx].strip()
            category = row[category_idx].strip()
            superset = row[superset_idx].strip()

            # Skip row if essential fields are missing
            if not state or not category or not superset:
                print(f"Skipping row {current_row_num}: Missing State, Category, or Superset.")
                continue

            # Collect all non-empty subset terms from the start index onwards
            all_subsets_for_row = []
            for subset_candidate in row[subset_start_idx:]: # Iterate from 'Subsets' col to end
                cleaned_subset = subset_candidate.strip()
                if cleaned_subset: # Only add if not empty after stripping
                    all_subsets_for_row.append(cleaned_subset)

            # Join collected subsets into a single comma-separated string
            combined_subsets_string = ",".join(all_subsets_for_row)

            # Write the processed row to the output file
            writer.writerow([state, category, superset, combined_subsets_string])
            processed_rows += 1

            # Optional: Print progress
            if processed_rows % 100 == 0:
                print(f"Processed {processed_rows} data rows...")

    print(f"\nFinished processing.")
    print(f"Successfully processed {processed_rows} data rows.")
    print(f"Consolidated dataset saved to '{OUTPUT_CSV_FILENAME}'.")
    print(f"You should now update CSV_FILE in app.py to '{OUTPUT_CSV_FILENAME}' if you haven't already.")


except FileNotFoundError as fnf_error:
    print(f"Error: {fnf_error}")
except ValueError as val_error:
    print(f"Error: {val_error}")
except Exception as e:
    print(f"An unexpected error occurred: {e}")
    import traceback
    traceback.print_exc() # Print full traceback for unexpected errors