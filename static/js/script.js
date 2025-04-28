// stereotype_quiz_app/static/js/script.js
// (No changes needed from the version provided earlier)

// Wait for the HTML document to be fully loaded before running the script
document.addEventListener('DOMContentLoaded', function() {

    // --- Toggle Subset Visibility ---
    const toggleButtons = document.querySelectorAll('.toggle-subsets');

    toggleButtons.forEach(button => {
        button.addEventListener('click', function() {
            const targetId = this.getAttribute('data-target');
            const targetElement = document.getElementById(targetId);

            if (targetElement) {
                if (targetElement.style.display === 'none' || targetElement.style.display === '') {
                    targetElement.style.display = 'block'; // Show the subsets
                    this.textContent = 'Hide Details'; // Change button text
                } else {
                    targetElement.style.display = 'none'; // Hide the subsets
                    this.textContent = 'Show Details'; // Change button text back
                }
            } else {
                console.error('Could not find subset target element with ID:', targetId);
            }
        });
    });

    // --- Show/Hide Offensiveness Rating Based on Annotation ---
    const annotationFieldsets = document.querySelectorAll('.annotation-options');

    annotationFieldsets.forEach(fieldset => {
        // Function to handle the logic, reusable for initial check and change event
        const handleAnnotationChange = (targetRadio) => {
            if (!targetRadio) return; // Exit if no radio button is involved

            const selectedValue = targetRadio.value;
            const questionIndex = fieldset.getAttribute('data-question-index');
            const ratingContainer = document.getElementById(`rating_container_${questionIndex}`);
            const ratingRadios = ratingContainer ? ratingContainer.querySelectorAll('input[type="radio"]') : [];

            if (ratingContainer) {
                if (selectedValue === 'Stereotype' && targetRadio.checked) {
                    ratingContainer.style.display = 'block'; // Show
                    ratingRadios.forEach(radio => radio.required = true); // Make required
                } else {
                    ratingContainer.style.display = 'none'; // Hide
                    ratingRadios.forEach(radio => {
                        radio.required = false; // Make not required
                        radio.checked = false; // Uncheck any selected rating
                    });
                }
            } else {
                console.error('Could not find rating container for index:', questionIndex);
            }
        };

        // Listen for changes within the fieldset
        fieldset.addEventListener('change', function(event) {
            // Ensure the event target is a radio button
            if (event.target.type === 'radio') {
                handleAnnotationChange(event.target);
            }
        });

        // Initial check on page load for pre-selected values (e.g., back button)
        const checkedRadio = fieldset.querySelector('input[type="radio"]:checked');
        if (checkedRadio) {
            handleAnnotationChange(checkedRadio);
        } else {
            // Ensure rating is hidden initially if nothing is checked
             const questionIndex = fieldset.getAttribute('data-question-index');
             const ratingContainer = document.getElementById(`rating_container_${questionIndex}`);
             if (ratingContainer) {
                 ratingContainer.style.display = 'none';
                 ratingContainer.querySelectorAll('input[type="radio"]').forEach(radio => radio.required = false);
             }
        }
    });

    // --- Enhanced Client-side Form Validation on Submit ---
    const quizForm = document.getElementById('quiz-form');
    if (quizForm) {
        quizForm.addEventListener('submit', function(event) {
            let firstErrorElement = null;
            let validationPassed = true;

            // 1. Check Familiarity Rating (Specific to quiz_cross.html)
            const familiarityRadios = quizForm.querySelectorAll('input[name="familiarity_rating"]');
            if (familiarityRadios.length > 0) { // Check if the element exists
                const familiaritySelected = Array.from(familiarityRadios).some(radio => radio.checked);
                if (!familiaritySelected) {
                    console.warn("Familiarity rating missing.");
                    validationPassed = false;
                    if (!firstErrorElement) {
                        const fieldset = familiarityRadios[0].closest('fieldset');
                        firstErrorElement = fieldset || familiarityRadios[0]; // Focus fieldset or first radio
                    }
                    // Optionally add visual error indication to familiarity fieldset
                    if (firstErrorElement.tagName === 'FIELDSET') firstErrorElement.style.borderColor = 'red';

                } else {
                     // Clear error indication if previously set
                     const fieldset = familiarityRadios[0].closest('fieldset');
                     if(fieldset) fieldset.style.borderColor = ''; // Reset border
                }
            }


            // 2. Check Each Annotation Group
            annotationFieldsets.forEach(fieldset => {
                 // Reset previous error indication if any
                 fieldset.style.borderColor = '';

                const questionIndex = fieldset.getAttribute('data-question-index');
                const radios = fieldset.querySelectorAll('input[type="radio"]');
                const isSelected = Array.from(radios).some(radio => radio.checked);

                if (!isSelected) {
                    console.warn(`Annotation missing for question index ${questionIndex}`);
                    validationPassed = false;
                    if (!firstErrorElement) firstErrorElement = fieldset;
                    fieldset.style.borderColor = 'red'; // Highlight missing annotation
                } else {
                     // 3. Check Offensiveness Rating *if* annotation is "Stereotype"
                     const stereotypeRadio = fieldset.querySelector('input[value="Stereotype"]');
                     if (stereotypeRadio && stereotypeRadio.checked) {
                         const ratingContainer = document.getElementById(`rating_container_${questionIndex}`);
                         const ratingFieldset = ratingContainer ? ratingContainer.querySelector('fieldset') : null;
                         if(ratingFieldset) ratingFieldset.style.borderColor = ''; // Reset border

                         const ratingRadios = ratingContainer ? ratingContainer.querySelectorAll('input[type="radio"]') : [];
                         const ratingSelected = Array.from(ratingRadios).some(radio => radio.checked);

                         if (!ratingSelected) {
                             console.warn(`Offensiveness rating missing for Stereotype at index ${questionIndex}`);
                             validationPassed = false;
                             if (!firstErrorElement) firstErrorElement = ratingContainer;
                             if (ratingFieldset) ratingFieldset.style.borderColor = 'red'; // Highlight missing rating
                         }
                     } else {
                         // Clear border if annotation is not Stereotype
                         const ratingContainer = document.getElementById(`rating_container_${questionIndex}`);
                         const ratingFieldset = ratingContainer ? ratingContainer.querySelector('fieldset') : null;
                          if(ratingFieldset) ratingFieldset.style.borderColor = '';
                     }
                }
            });

             // If validation failed, prevent submission and alert/focus
             if (!validationPassed) {
                 event.preventDefault(); // Stop the form submission
                 alert('Please complete all required fields (*), including familiarity and all annotations/ratings where applicable.');

                 // Scroll to and focus the first element with an issue
                 if (firstErrorElement) {
                     firstErrorElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
                     // Add temporary outline/focus indication
                     firstErrorElement.style.outline = '2px solid red';
                     setTimeout(() => {
                         firstErrorElement.style.outline = '';
                         // Reset border colors on timeout as well
                         document.querySelectorAll('fieldset[style*="border-color: red"]').forEach(el => el.style.borderColor = '');
                        }, 3000);
                 }
             }
        });
    }

}); // End of DOMContentLoaded