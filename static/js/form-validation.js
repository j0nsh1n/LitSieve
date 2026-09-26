document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('form.auth-form[novalidate]').forEach(function (form, formIndex) {
        var fields = Array.from(form.querySelectorAll('input[required], input[minlength], input[type="email"]'));

        function errorId(input) {
            return 'auth-field-error-' + formIndex + '-' + input.name;
        }

        function clearError(input) {
            var id = errorId(input);
            var message = document.getElementById(id);
            if (message) message.remove();
            input.removeAttribute('aria-invalid');
            var describedBy = (input.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean);
            describedBy = describedBy.filter(function (part) { return part !== id; });
            if (describedBy.length) input.setAttribute('aria-describedby', describedBy.join(' '));
            else input.removeAttribute('aria-describedby');
        }

        function wordsFor(input) {
            var validity = input.validity;
            if (validity.valueMissing) {
                if (input.type === 'email') return 'Enter your email address';
                if (input.name === 'username' && form.action.includes('/reset-password/')) {
                    return 'Enter your username or email';
                }
                if (input.name === 'username') return 'Enter your username';
                if (input.name === 'token') return 'Enter your reset code';
                if (input.name === 'password_confirm') return 'Confirm your password';
                return 'Enter your password';
            }
            if (validity.tooShort) return 'Use at least ' + input.minLength + ' characters';
            if (validity.tooLong) return 'Use no more than ' + input.maxLength + ' characters';
            if (validity.typeMismatch) return 'Enter a valid email address';
            if (validity.patternMismatch) return 'Use only letters, numbers, periods, underscores, plus signs, or hyphens';
            if (validity.customError) return input.validationMessage;
            return 'Check this field';
        }

        function showError(input) {
            var id = errorId(input);
            var message = document.getElementById(id);
            if (!message) {
                message = document.createElement('div');
                message.id = id;
                message.className = 'auth-error auth-field-error';
                message.setAttribute('role', 'alert');
                input.after(message);
            }
            message.textContent = wordsFor(input);
            input.setAttribute('aria-invalid', 'true');
            var describedBy = (input.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean);
            if (!describedBy.includes(id)) describedBy.push(id);
            input.setAttribute('aria-describedby', describedBy.join(' '));
        }

        function checkConfirmation() {
            var password = form.elements.namedItem('password');
            var confirmation = form.elements.namedItem('password_confirm');
            if (!password || !confirmation) return;
            confirmation.setCustomValidity('');
            if (confirmation.value && password.checkValidity() && confirmation.checkValidity() &&
                confirmation.value !== password.value) {
                confirmation.setCustomValidity('The two passwords do not match');
            }
        }

        fields.forEach(function (input) {
            input.addEventListener('input', function () {
                checkConfirmation();
                if (document.getElementById(errorId(input))) {
                    if (input.checkValidity()) clearError(input);
                    else showError(input);
                }
                var confirmation = form.elements.namedItem('password_confirm');
                if (confirmation && confirmation !== input && document.getElementById(errorId(confirmation))) {
                    if (confirmation.checkValidity()) clearError(confirmation);
                    else showError(confirmation);
                }
            });
        });

        form.addEventListener('submit', function (event) {
            checkConfirmation();
            var firstInvalid = null;
            fields.forEach(function (input) {
                if (input.checkValidity()) clearError(input);
                else {
                    showError(input);
                    if (!firstInvalid) firstInvalid = input;
                }
            });
            if (firstInvalid) {
                event.preventDefault();
                firstInvalid.focus();
            }
        });
    });
});
