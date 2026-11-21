/* Parthenon UX prototype — workflow generation model pickers + skill/SOP editor entry
   points (relocated). Loaded by Skills & SOPs and by System (authoring model section). */
const wfState = {
  systemModel: '',
  options: [
    { modelId: 'gpt-4.1', configDisplayName: 'OpenAI Production' },
    { modelId: 'gpt-4.1-mini', configDisplayName: 'OpenAI Production' },
    { modelId: 'claude-sonnet-4', configDisplayName: 'Anthropic Primary' },
    { modelId: 'claude-opus-4', configDisplayName: 'Anthropic Primary' },
    { modelId: 'gemini-2.5-pro', configDisplayName: 'Google Gemini Production' },
    { modelId: 'gemini-2.5-flash', configDisplayName: 'Google Gemini Production' },
    { modelId: 'mistral-large-latest', configDisplayName: 'Mistral AI Production' },
    { modelId: 'mistral-medium-latest', configDisplayName: 'Mistral AI Production' },
    { modelId: 'command-r-plus', configDisplayName: 'Cohere Production' },
    { modelId: 'command-r', configDisplayName: 'Cohere Production' },
    { modelId: 'deepseek-chat', configDisplayName: 'DeepSeek Production' },
    { modelId: 'deepseek-reasoner', configDisplayName: 'DeepSeek Production' },
    { modelId: 'sonar-pro', configDisplayName: 'Perplexity Production' }
  ]
};

function wfById(id) {
  return document.getElementById(id);
}

function wfPopulateSystemModels() {
  const select = wfById('wf-system-model');
  if (!select) return;
  const options = ['<option value="">Not configured</option>'];
  wfState.options.forEach((option) => {
    const selected = option.modelId === wfState.systemModel ? ' selected' : '';
    options.push('<option value="' + option.modelId + '"' + selected + '>' + option.modelId + ' (' + option.configDisplayName + ')</option>');
  });
  select.innerHTML = options.join('');
}

function wfSetModelFromSelect(value) {
  wfState.systemModel = value;
}

function wfSaveSystemModel() {
  wfState.systemModel = wfById('wf-system-model').value;
  wfSyncPreviewHeader();
}

function wfSyncPreviewHeader() {
  const modelLabel = wfState.systemModel || '-';
  const title = wfById('wf-preview-title');
  if (title) {
    title.textContent = 'Workflow Preview (Model: ' + modelLabel + ')';
  }
}

function wfEnsureModel(type) {
  if (wfState.systemModel) return true;
  const target = type === 'skill' ? wfById('wf-skill-error') : wfById('wf-sop-error');
  if (target) {
    target.textContent = 'Workflow generation model is not configured. Configure it in system settings.';
    target.style.display = 'block';
  }
  return false;
}

function wfClearError(type) {
  const target = type === 'skill' ? wfById('wf-skill-error') : wfById('wf-sop-error');
  if (target) {
    target.textContent = '';
    target.style.display = 'none';
  }
}

function wfOpenEditor(type) {
  wfClearError(type);
  openModal(type === 'skill' ? 'modal-wf-skill-editor' : 'modal-wf-sop-editor');
}

function wfGenerate(type) {
  if (!wfEnsureModel(type)) return;
  wfClearError(type);

  if (type === 'skill') {
    const description = wfById('wf-skill-description').value.trim();
    const tools = Array.from(document.querySelectorAll('.wf-skill-tool:checked')).map((el) => el.value);
    if (!description || tools.length === 0) return;
    const lines = tools.map((tool, idx) => (idx + 1) + '. Use tool ' + tool + ' to execute the requested task scope.');
    wfById('wf-skill-workflow').value = 'Workflow Objective: ' + description + '\n\n' + lines.join('\n');
    return;
  }

  const description = wfById('wf-sop-description').value.trim();
  const steps = Array.from(document.querySelectorAll('.wf-sop-step:checked')).map((el) => el.value);
  if (!description || steps.length === 0) return;
  const lines = steps.map((step, idx) => (idx + 1) + '. Execute step: ' + step + '.');
  wfById('wf-sop-workflow').value = 'Workflow Objective: ' + description + '\n\n' + lines.join('\n');
}

function wfPreview(type) {
  if (!wfEnsureModel(type)) return;
  wfClearError(type);

  const model = wfState.systemModel || '-';
  wfById('wf-preview-title').textContent = 'Workflow Preview (Model: ' + model + ')';

  if (type === 'skill') {
    const name = wfById('wf-skill-name').value;
    const description = wfById('wf-skill-description').value;
    const workflow = wfById('wf-skill-workflow').value;
    const tools = Array.from(document.querySelectorAll('.wf-skill-tool:checked')).map((el) => el.value).join(', ');
    wfById('wf-preview-content').textContent = [
      '# Skill Workflow File',
      '',
      'Name: ' + name,
      'Description: ' + description,
      'Selected Tools: ' + tools,
      '',
      'Formatted Instruction',
      '---',
      workflow
    ].join('\n');
    openModal('modal-wf-preview');
    return;
  }

  const name = wfById('wf-sop-name').value;
  const description = wfById('wf-sop-description').value;
  const workflow = wfById('wf-sop-workflow').value;
  const steps = Array.from(document.querySelectorAll('.wf-sop-step:checked')).map((el) => el.value).join(', ');
  wfById('wf-preview-content').textContent = [
    '# SOP Workflow File',
    '',
    'Name: ' + name,
    'Description: ' + description,
    'Selected Steps: ' + steps,
    '',
    'Formatted Instruction',
    '---',
    workflow
  ].join('\n');
  openModal('modal-wf-preview');
}

function wfOpenPreviewOnly(type) {
  wfPreview(type);
}

wfPopulateSystemModels();
wfSyncPreviewHeader();

// ════════════════════════════════════════════════════════════════