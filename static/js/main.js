function loadTemplateContent() {
    var clientId = document.getElementById('client_id').value;
    var templateName = document.getElementById('template_name').value;
    
    if (templateName && clientId) {
        $.ajax({
            url: '/load_client',
            type: 'POST',
            data: {
                client_id: clientId,
                template_name: templateName
            },
            success: function(response) {
                if (response.prompt && response.prompt_name) {
                    document.getElementById('custom_prompt').value = response.prompt;
                    document.getElementById('prompt_name_group').style.display = 'none';
                } else {
                    document.getElementById('custom_prompt').value = '';
                    document.getElementById('prompt_name_group').style.display = 'block';
                    document.getElementById('prompt_name').value = 'Custom';
                    alert('No prompt associated with this template; please select or create a prompt');
                }
            },
            error: function() {
                document.getElementById('custom_prompt').value = '';
                document.getElementById('prompt_name_group').style.display = 'block';
                document.getElementById('prompt_name').value = 'Custom';
                alert('Error loading prompt for template');
            }
        });
    } else {
        document.getElementById('custom_prompt').value = '';
        document.getElementById('prompt_name_group').style.display = 'block';
        document.getElementById('prompt_name').value = 'Custom';
    }
}

function loadPromptContent() {
    var clientId = document.getElementById('client_id').value;
    var promptName = document.getElementById('prompt_name').value;
    
    if (promptName && promptName !== 'Custom' && clientId) {
        $.ajax({
            url: '/load_client',
            type: 'POST',
            data: {
                client_id: clientId,
                prompt_name: promptName
            },
            success: function(response) {
                if (response.prompt) {
                    document.getElementById('custom_prompt').value = response.prompt;
                } else {
                    document.getElementById('custom_prompt').value = '';
                    alert('Failed to load prompt content');
                }
            },
            error: function() {
                document.getElementById('custom_prompt').value = '';
                alert('Error loading prompt content');
            }
        });
    } else {
        document.getElementById('custom_prompt').value = '';
    }
}

function toggleTemplateUpload() {
    var templateUpload = document.getElementById('templateUpload');
    templateUpload.style.display = templateUpload.style.display === 'none' ? 'block' : 'none';
    document.getElementById('template_name').value = '';
    document.getElementById('prompt_name_group').style.display = 'block';
    document.getElementById('prompt_name').value = 'Custom';
    document.getElementById('custom_prompt').value = '';
}