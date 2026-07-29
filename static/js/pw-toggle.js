// "Show password" checkbox on the login / register / reset-password forms.
// Extracted from inline <script> so the CSP can drop 'unsafe-inline'.
document.addEventListener('DOMContentLoaded', function () {
    var box = document.getElementById('show-pw');
    if (!box) return;
    box.addEventListener('change', function () {
        var type = this.checked ? 'text' : 'password';
        document.querySelectorAll('.pw-field').forEach(function (el) {
            el.type = type;
        });
    });
});
