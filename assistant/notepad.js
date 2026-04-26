const { ipcRenderer } = require('electron');

document.addEventListener('DOMContentLoaded', () => {
    const minBtn = document.getElementById('minBtn');
    const maxBtn = document.getElementById('maxBtn');
    const closeBtn = document.getElementById('closeBtn');
    const saveBtn = document.getElementById('saveBtn');
    const noteContent = document.getElementById('noteContent');
    const wordCount = document.getElementById('wordCount');
    const charCount = document.getElementById('charCount');
    const saveStatus = document.getElementById('saveStatus');
    const saveDot = document.getElementById('saveDot');

    // Window controls
    minBtn.addEventListener('click', () => {
        ipcRenderer.send('notepad-minimize');
    });

    maxBtn.addEventListener('click', () => {
        ipcRenderer.send('notepad-maximize');
    });

    closeBtn.addEventListener('click', () => {
        ipcRenderer.send('notepad-close');
    });

    // Update words and chars
    noteContent.addEventListener('input', () => {
        const text = noteContent.value;
        charCount.textContent = text.length;
        const words = text.trim() === '' ? 0 : text.trim().split(/\s+/).length;
        wordCount.textContent = words;
        
        saveStatus.textContent = 'Editing...';
        saveDot.style.backgroundColor = '#ffdf8c'; // Yellow while editing
    });

    // Save button
    saveBtn.addEventListener('click', () => {
        saveStatus.textContent = 'Auto-saved just now';
        saveDot.style.backgroundColor = '#b5e48c'; // Green when saved
        
        // Notify backend of save
        ipcRenderer.send('notepad-save', {
            title: document.getElementById('noteTitle').value,
            content: noteContent.value
        });
    });

    // Listen for text injections from AI
    ipcRenderer.on('notepad-insert', (event, text) => {
        const start = noteContent.selectionStart;
        const end = noteContent.selectionEnd;
        const currentText = noteContent.value;
        
        // Insert text at cursor position
        noteContent.value = currentText.substring(0, start) + text + currentText.substring(end);
        
        // Move cursor after inserted text
        noteContent.selectionStart = noteContent.selectionEnd = start + text.length;
        
        // Trigger input event to update counts
        noteContent.dispatchEvent(new Event('input'));
    });

    // Listen for clear command from AI (when starting a fresh draft)
    ipcRenderer.on('notepad-clear', () => {
        noteContent.value = '';
        noteTitle.value = 'New Note';
        noteContent.dispatchEvent(new Event('input'));
    });

    // Listen for title set command from AI
    ipcRenderer.on('notepad-title', (event, title) => {
        noteTitle.value = title;
    });
});
