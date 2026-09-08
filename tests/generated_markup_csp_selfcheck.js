const assert = require('assert');
const fs = require('fs');

const sources = {
    auth: fs.readFileSync('frontend/auth.js', 'utf8'),
    admin: fs.readFileSync('frontend/js/admin_panel.js', 'utf8'),
    adminOperations: fs.readFileSync('frontend/js/admin_operations.js', 'utf8'),
    form: fs.readFileSync('frontend/js/form_renderer.js', 'utf8'),
    template: fs.readFileSync('frontend/js/template_config.js', 'utf8'),
};
const css = fs.readFileSync('frontend/css/windows-ui.css', 'utf8');

for (const [name, source] of Object.entries(sources)) {
    assert.doesNotMatch(source, /<[^>]*\bon[a-z]+\s*=/i, `${name} generated markup must not contain event attributes.`);
    assert.doesNotMatch(source, /<[^>]*\bstyle\s*=/i, `${name} generated markup must not contain style attributes.`);
}

for (const preservedCall of [
    'markNotificationRead(Number(trigger.dataset.notificationId))',
    'openChangePasswordModal(Number(trigger.dataset.userId), trigger.dataset.username)',
    'openConfigModal(Number(trigger.dataset.templateId), decodeURIComponent(trigger.dataset.templateName))',
    "revokeAssignments(Number(trigger.dataset.userId), 'reviewer')",
    'toggleSubmissionSelection(Number(trigger.dataset.submissionId), trigger.checked)',
]) {
    assert(
        sources.auth.includes(preservedCall) || sources.admin.includes(preservedCall),
        `Generated action must preserve its public call and arguments: ${preservedCall}.`,
    );
}

assert(sources.template.includes('data-template-action="remove-rule"'));
assert(sources.template.includes('data-template-action="delete-dictionary-item"'));
assert(sources.form.includes('generated-transition-icon-lg'));
assert(sources.form.includes('generated-transition-icon-sm'));
assert(sources.template.includes('generated-checkbox-emphasis'));

for (const className of [
    '.generated-checkbox-emphasis',
    '.generated-transition-icon-lg',
    '.generated-transition-icon-sm',
    '.generated-submission-path-cell',
    '.generated-submission-actions-cell',
]) {
    assert(css.includes(className), `Generated markup class must be defined: ${className}.`);
}

console.log('Generated markup CSP self-check passed.');
