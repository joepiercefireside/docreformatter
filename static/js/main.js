function loadPromptContent() {
    var clientId = document.getElementById('client_id').value;
    var promptName = document.getElementById('prompt_name').value;
    
    if (promptName && clientId) {
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