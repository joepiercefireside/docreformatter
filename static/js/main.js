function updatePrompts() {
    const templateSelect = document.getElementById('template');
    const templatePrompt = document.getElementById('template_prompt');
    const conversionPrompt = document.getElementById('conversion_prompt');
    if (templateSelect && templatePrompt && conversionPrompt) {
        const selectedTemplate = templateSelect.options[templateSelect.selectedIndex];
        if (selectedTemplate && selectedTemplate.dataset.prompt) {
            templatePrompt.value = selectedTemplate.dataset.prompt.replace(/\\n/g, '\n');
            conversionPrompt.value = selectedTemplate.dataset.conversion ? selectedTemplate.dataset.conversion.replace(/\\n/g, '\n') : '';
        } else {
            templatePrompt.value = '';
            conversionPrompt.value = '';
        }
    }
}

function loadTemplateContent() {
    const clientId = document.getElementById('client') ? document.getElementById('client').value : '';
    const templateId = document.getElementById('template') ? document.getElementById('template').value : '';
    
    if (templateId) {
        fetch('/load_client', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: new URLSearchParams({
                'client_id': clientId,
                'template_id': templateId
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.prompt && data.prompt_name) {
                document.getElementById('template_prompt').value = data.prompt;
            } else {
                document.getElementById('template_prompt').value = '';
                alert('No prompt associated with this template');
            }
        })
        .catch(error => {
            document.getElementById('template_prompt').value = '';
            alert('Error loading template prompt');
        });
    } else {
        document.getElementById('template_prompt').value = '';
    }
}