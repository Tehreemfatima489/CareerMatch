
let questionCount = 0;

// Toggle panel on/off
document.getElementById("toggle-assessment").addEventListener("change", function () {
    const panel = document.getElementById("assessmentPanel");
    if (this.checked) {
    panel.classList.add("active");
    if (questionCount === 0) addQuestion(); // auto-add first question
    } else {
    panel.classList.remove("active");
    }
});

function addQuestion() {
    questionCount++;
    const n = questionCount;
    const container = document.getElementById("questionsContainer");

    const card = document.createElement("div");
    card.className = "question-card";
    card.id = `qcard_${n}`;

    card.innerHTML = `
    <button type="button" class="remove-q-btn" onclick="removeQuestion(${n})" title="Remove question">✕</button>
    <div class="q-number">Question ${n}</div>

    <textarea name="question_${n}" placeholder="Enter your question here…" required></textarea>

    <div class="options-grid">
        <div class="option-row">
        <span class="option-badge">A</span>
        <input type="text" name="option_a_${n}" placeholder="Option A" required>
        </div>
        <div class="option-row">
        <span class="option-badge">B</span>
        <input type="text" name="option_b_${n}" placeholder="Option B" required>
        </div>
        <div class="option-row">
        <span class="option-badge">C</span>
        <input type="text" name="option_c_${n}" placeholder="Option C" required>
        </div>
        <div class="option-row">
        <span class="option-badge">D</span>
        <input type="text" name="option_d_${n}" placeholder="Option D" required>
        </div>
    </div>

    <div class="correct-row">
        <label for="correct_${n}">✅ Correct Answer:</label>
        <select name="correct_${n}" id="correct_${n}" required>
        <option value="">— select —</option>
        <option value="A">A</option>
        <option value="B">B</option>
        <option value="C">C</option>
        <option value="D">D</option>
        </select>
    </div>
    `;

    container.appendChild(card);
}

function removeQuestion(n) {
    const card = document.getElementById(`qcard_${n}`);
    if (card) card.remove();
}
