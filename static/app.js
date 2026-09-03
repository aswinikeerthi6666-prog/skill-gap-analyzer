const analyzeBtn = document.getElementById('analyzeBtn');
const btnLabel = analyzeBtn.querySelector('.btn-label');
const btnSpinner = analyzeBtn.querySelector('.btn-spinner');
const errorMsg = document.getElementById('errorMsg');
const saveStatus = document.getElementById('saveStatus');
const emptyState = document.getElementById('emptyState');
const results = document.getElementById('results');

const IS_SIGNED_IN = !!window.IS_SIGNED_IN;
let currentAnalysisId = null;
let currentFullData = null;
let currentJobDescription = '';

function setLoading(isLoading) {
  analyzeBtn.disabled = isLoading;
  btnSpinner.hidden = !isLoading;
  btnLabel.textContent = isLoading ? 'Analyzing…' : 'Analyze the gap';
}

function showError(message) {
  errorMsg.textContent = message;
  errorMsg.hidden = false;
}

function clearError() {
  errorMsg.hidden = true;
  errorMsg.textContent = '';
}

function showSaveStatus(message) {
  saveStatus.textContent = message;
  saveStatus.hidden = false;
  setTimeout(() => { saveStatus.hidden = true; }, 2500);
}

analyzeBtn.addEventListener('click', async () => {
  clearError();
  const job_description = document.getElementById('job').value.trim();
  const current_skills = document.getElementById('skills').value.trim();

  if (!job_description || !current_skills) {
    showError('Please fill in both the job description and your current skills.');
    return;
  }

  setLoading(true);
  emptyState.hidden = true;
  results.hidden = true;
  currentAnalysisId = null;

  try {
    const res = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_description, current_skills }),
    });

    const data = await res.json();

    if (!res.ok) {
      showError(data.error || 'Something went wrong. Please try again.');
      emptyState.hidden = false;
      return;
    }

    renderResults(data, job_description, {});

    if (IS_SIGNED_IN) {
      const saved = await saveAnalysisToServer(data, job_description, {});
      if (saved) {
        currentAnalysisId = saved.analysis_id;
        showSaveStatus('Saved to your account.');
      }
    }
  } catch (err) {
    console.error(err);
    showError('Could not reach the server. Is the Flask app running?');
    emptyState.hidden = false;
  } finally {
    setLoading(false);
  }
});

async function saveAnalysisToServer(analysisData, jobDescription, progress) {
  try {
    const res = await fetch('/api/save-analysis', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        analysis: analysisData,
        job_description: jobDescription,
        progress: progress,
        analysis_id: currentAnalysisId || undefined,
      }),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (err) {
    console.error('Save failed', err);
    return null;
  }
}

function renderResults(data, job_description, existingProgress) {
  currentFullData = data;
  currentJobDescription = job_description;

  document.getElementById('matchPercent').textContent = data.overall_match_percent ?? '–';

  const matchedWrap = document.getElementById('matchedSkills');
  matchedWrap.innerHTML = '';
  (data.matched_skills || []).forEach((skill) => {
    const span = document.createElement('span');
    span.textContent = skill;
    matchedWrap.appendChild(span);
  });

  const gapsList = document.getElementById('gapsList');
  gapsList.innerHTML = '';
  (data.skill_gaps || []).forEach((gap) => {
    const li = document.createElement('li');
    const dot = document.createElement('span');
    dot.className = `priority-dot priority-${gap.priority || 'medium'}`;
    const content = document.createElement('div');
    content.className = 'gap-content';
    content.innerHTML = `<strong>${escapeHtml(gap.skill)}</strong><p>${escapeHtml(gap.why_it_matters || '')}</p>`;
    li.appendChild(dot);
    li.appendChild(content);
    gapsList.appendChild(li);
  });

  renderPlan(data.learning_plan || [], data.overall_match_percent, job_description, existingProgress || {});
  renderQuiz(data.quiz || []);

  results.hidden = false;
}

// --- Local (anonymous, not signed in) progress storage -------------------
function progressKey(jobDescription) {
  let hash = 0;
  for (let i = 0; i < jobDescription.length; i++) {
    hash = (hash * 31 + jobDescription.charCodeAt(i)) | 0;
  }
  return `skillgap_progress_${hash}`;
}

function loadLocalProgress(key) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function saveLocalProgress(key, progress) {
  try {
    localStorage.setItem(key, JSON.stringify(progress));
  } catch {
    // ignore storage errors (e.g. private browsing)
  }
}

function buildResourceUrl(step) {
  const query = step.resource_query || step.title;
  const platformHint = step.resource_type ? `${step.resource_type} ` : '';
  return `https://www.google.com/search?q=${encodeURIComponent(platformHint + query)}`;
}

// Normalizes progress objects coming back from the server (JSON keys are
// always strings) so `progress[0]` and `progress["0"]` both work.
function normalizeProgress(raw) {
  const out = {};
  Object.keys(raw || {}).forEach((k) => {
    out[Number(k)] = raw[k];
  });
  return out;
}

function renderPlan(steps, matchPercent, jobDescription, existingProgress) {
  const planList = document.getElementById('planList');
  const progressLabel = document.getElementById('planProgress');
  const progressFill = document.getElementById('progressFill');
  planList.innerHTML = '';

  const localKey = progressKey(jobDescription || String(matchPercent));
  const hasExisting = Object.keys(existingProgress || {}).length > 0;
  const progress = hasExisting
    ? normalizeProgress(existingProgress)
    : (IS_SIGNED_IN ? {} : loadLocalProgress(localKey));

  function stepIsDone(index) {
    const p = progress[index] || {};
    return !!(p.watched && p.practiced);
  }

  function persist() {
    if (IS_SIGNED_IN && currentFullData) {
      saveAnalysisToServer(currentFullData, currentJobDescription, progress).then((saved) => {
        if (saved) currentAnalysisId = saved.analysis_id;
      });
    } else {
      saveLocalProgress(localKey, progress);
    }
  }

  function updateProgressBar() {
    const total = steps.length;
    const done = steps.filter((_, i) => stepIsDone(i)).length;
    progressLabel.textContent = `${done} of ${total} done`;
    progressFill.style.width = total ? `${(done / total) * 100}%` : '0%';
  }

  steps.forEach((step, index) => {
    const li = document.createElement('li');
    if (stepIsDone(index)) li.classList.add('plan-done');

    const stepNumber = document.createElement('div');
    stepNumber.className = 'plan-step-number' + (stepIsDone(index) ? ' step-done' : '');
    stepNumber.textContent = stepIsDone(index) ? '✓' : String(index + 1);

    const content = document.createElement('div');
    content.className = 'plan-content';

    const resourceUrl = buildResourceUrl(step);
    const resourceTypeLabel = step.resource_type ? escapeHtml(step.resource_type) : 'resource';

    content.innerHTML = `
      <strong>${escapeHtml(step.title)}</strong>
      <p>${escapeHtml(step.detail || '')}</p>
      <a class="resource-link" href="${resourceUrl}" target="_blank" rel="noopener noreferrer">
        <span class="resource-type-tag">${resourceTypeLabel} →</span>find it
      </a>
    `;

    const checksRow = document.createElement('div');
    checksRow.className = 'plan-checks';

    function afterToggle() {
      const done = stepIsDone(index);
      li.classList.toggle('plan-done', done);
      stepNumber.classList.toggle('step-done', done);
      stepNumber.textContent = done ? '✓' : String(index + 1);
      persist();
      updateProgressBar();
    }

    const watchedPill = makePill('Watched', !!(progress[index] || {}).watched, () => {
      progress[index] = progress[index] || {};
      progress[index].watched = !progress[index].watched;
      afterToggle();
    });

    const practicedPill = makePill('Practiced', !!(progress[index] || {}).practiced, () => {
      progress[index] = progress[index] || {};
      progress[index].practiced = !progress[index].practiced;
      afterToggle();
    });

    checksRow.appendChild(watchedPill);
    checksRow.appendChild(practicedPill);

    // Insert the checks row right after the title/detail, before the link
    const linkEl = content.querySelector('.resource-link');
    content.insertBefore(checksRow, linkEl);

    li.appendChild(stepNumber);
    li.appendChild(content);
    planList.appendChild(li);
  });

  updateProgressBar();
}

function makePill(label, isOn, onToggle) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'check-pill' + (isOn ? ' on' : '');
  btn.innerHTML = `<span class="dot"></span>${label}`;
  btn.addEventListener('click', () => {
    const nowOn = !btn.classList.contains('on');
    btn.classList.toggle('on', nowOn);
    onToggle();
  });
  return btn;
}

function renderQuiz(questions) {
  const quizWrap = document.getElementById('quiz');
  const scoreWrap = document.getElementById('quizScore');
  quizWrap.innerHTML = '';
  scoreWrap.hidden = true;

  let answered = 0;
  let correctCount = 0;

  questions.forEach((q, qIndex) => {
    const qDiv = document.createElement('div');
    qDiv.className = 'quiz-question';

    const qText = document.createElement('p');
    qText.className = 'q-text';
    qText.textContent = `${qIndex + 1}. ${q.question}`;
    qDiv.appendChild(qText);

    const optsDiv = document.createElement('div');
    optsDiv.className = 'quiz-options';

    const explanation = document.createElement('p');
    explanation.className = 'quiz-explanation';
    explanation.hidden = true;
    explanation.textContent = q.explanation || '';

    q.options.forEach((optionText, optIndex) => {
      const btn = document.createElement('button');
      btn.className = 'quiz-option';
      btn.textContent = optionText;
      btn.addEventListener('click', () => {
        const buttons = optsDiv.querySelectorAll('.quiz-option');
        buttons.forEach((b) => (b.disabled = true));

        if (optIndex === q.correct_index) {
          btn.classList.add('correct');
          correctCount++;
        } else {
          btn.classList.add('incorrect');
          buttons[q.correct_index].classList.add('correct');
        }

        explanation.hidden = false;
        answered++;

        if (answered === questions.length) {
          scoreWrap.hidden = false;
          scoreWrap.textContent = `You got ${correctCount} out of ${questions.length} right.`;
        }
      });
      optsDiv.appendChild(btn);
    });

    qDiv.appendChild(optsDiv);
    qDiv.appendChild(explanation);
    quizWrap.appendChild(qDiv);
  });
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str ?? '';
  return div.innerHTML;
}

// --- Load a saved analysis from the dashboard (?load=<analysis_id>) ------
async function loadFromQueryParam() {
  const params = new URLSearchParams(window.location.search);
  const loadId = params.get('load');
  if (!loadId || !IS_SIGNED_IN) return;

  try {
    const res = await fetch(`/api/analysis/${encodeURIComponent(loadId)}`);
    if (!res.ok) return;
    const item = await res.json();

    currentAnalysisId = item.analysis_id;
    document.getElementById('job').value = item.job_description || '';

    emptyState.hidden = true;
    renderResults(item.analysis, item.job_description || '', item.progress || {});
  } catch (err) {
    console.error('Failed to load saved analysis', err);
  }
}

loadFromQueryParam();