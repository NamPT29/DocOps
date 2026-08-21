const assert = require('assert');
const fs = require('fs');

const html = fs.readFileSync('frontend/index.html', 'utf8');
const app = fs.readFileSync('frontend/app.js', 'utf8');
const formRenderer = fs.readFileSync('frontend/js/form_renderer.js', 'utf8');
const workspace = fs.readFileSync('frontend/js/project_workspace.js', 'utf8');

assert(html.includes('id="employeeProjectSelect"'));
assert(html.includes('onchange="onEmployeeProjectSelected()"'));
assert(html.includes('js/project_workspace.js'));
assert(app.includes('await initializeEmployeeProjectWorkspace()'));
assert(formRenderer.includes('window.activeProjectWorkspace'));
assert(workspace.includes('/api/projects/${safeProjectId}/workspace'));
assert(workspace.includes('window.activeTemplateId = response.data.project.template_id'));
assert(workspace.includes("templateContainer.style.setProperty('display', 'none', 'important')"));
assert(workspace.includes("manualUploadLabel.classList.add('d-none')"));

console.log('project workspace self-check passed');
