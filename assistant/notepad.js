const { ipcRenderer } = require('electron');

document.addEventListener('DOMContentLoaded', () => {
    // Window controls
    const minBtn = document.getElementById('minBtn');
    const maxBtn = document.getElementById('maxBtn');
    const closeBtn = document.getElementById('closeBtn');

    minBtn.addEventListener('click', () => ipcRenderer.send('notepad-minimize'));
    maxBtn.addEventListener('click', () => ipcRenderer.send('notepad-maximize'));
    closeBtn.addEventListener('click', () => ipcRenderer.send('notepad-close'));

    // Tab Navigation
    const navItems = document.querySelectorAll('.nav-item');
    const panels = document.querySelectorAll('.content-panel');

    navItems.forEach(item => {
        item.addEventListener('click', () => {
            // Remove active from all
            navItems.forEach(nav => nav.classList.remove('active'));
            panels.forEach(panel => panel.classList.remove('active'));

            // Add active to clicked
            item.classList.add('active');
            const targetId = item.getAttribute('data-target');
            document.getElementById(targetId).classList.add('active');
        });
    });

    // Notes Logic
    const saveBtn = document.getElementById('saveBtn');
    const noteContent = document.getElementById('noteContent');
    const noteTitle = document.getElementById('noteTitle');
    const wordCount = document.getElementById('wordCount');
    const saveStatus = document.getElementById('saveStatus');

    noteContent.addEventListener('input', () => {
        const text = noteContent.value;
        const words = text.trim() === '' ? 0 : text.trim().split(/\s+/).length;
        wordCount.textContent = words;
        
        saveStatus.textContent = 'Editing...';
        saveStatus.style.color = '#ffbd2e'; // Yellow while editing
    });

    saveBtn.addEventListener('click', () => {
        saveStatus.textContent = 'Saved just now';
        saveStatus.style.color = 'var(--accent-green)'; // Green when saved
        
        ipcRenderer.send('notepad-save', {
            title: noteTitle.value,
            content: noteContent.value
        });
    });

    // ESP32 Logic
    const pingEspBtn = document.getElementById('pingEspBtn');
    if (pingEspBtn) {
        pingEspBtn.addEventListener('click', () => {
            // We will wire this to backend via IPC later
            alert("Sent Ping to ESP32! (Backend wiring in progress)");
        });
    }

    // AI IPC Receivers (Compatibility)
    ipcRenderer.on('notepad-insert', (event, text) => {
        const start = noteContent.selectionStart;
        const end = noteContent.selectionEnd;
        const currentText = noteContent.value;
        
        noteContent.value = currentText.substring(0, start) + text + currentText.substring(end);
        noteContent.selectionStart = noteContent.selectionEnd = start + text.length;
        noteContent.dispatchEvent(new Event('input'));
        
        // Auto-switch to notes panel
        document.querySelector('[data-target="panel-notes"]').click();
    });

    ipcRenderer.on('notepad-clear', () => {
        noteContent.value = '';
        noteTitle.value = 'New Note';
        noteContent.dispatchEvent(new Event('input'));
    });

    ipcRenderer.on('notepad-title', (event, title) => {
        noteTitle.value = title;
    });

    ipcRenderer.on('notepad-draw', (event, imageUrl) => {
        const paintArea = document.getElementById('paintArea');
        paintArea.innerHTML = `<img src="${imageUrl}" style="max-width:100%; max-height:100%; object-fit:contain; border-radius:10px;" />`;
        document.querySelector('[data-target="panel-paint"]').click();
    });
});
