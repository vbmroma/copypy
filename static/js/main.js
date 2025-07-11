document.addEventListener('DOMContentLoaded', function() {
    var socket = io();

    // --- Referências aos elementos da UI ---
    const operationStatus = document.getElementById('operationStatus');
    const progressBar = document.getElementById('progressBar');
    const filesProcessed = document.getElementById('filesProcessed');
    const totalFilesEstimated = document.getElementById('totalFilesEstimated');
    const currentDirectory = document.getElementById('currentDirectory');
    const logMessages = document.getElementById('logMessages');
    const dynamicAlerts = document.getElementById('dynamicAlerts'); 

    const startCollectionBtn = document.getElementById('startCollectionBtn');
    const startComparisonBtn = document.getElementById('startComparisonBtn');
    const startCopyBtn = document.getElementById('startCopyBtn'); 

    const pauseBtn = document.getElementById('pauseBtn');
    const resumeBtn = document.getElementById('resumeBtn');
    const stopBtn = document.getElementById('stopBtn');

    const jsonOrigemSelect = document.getElementById('jsonOrigem');
    const jsonDestinoSelect = document.getElementById('jsonDestino');
    const comparisonJsonForCopySelect = document.getElementById('comparisonJsonForCopy');
    const collectedJsonsList = document.getElementById('collectedJsonsList');
    const comparisonJsonsList = document.getElementById('comparisonJsonsList');
    const copyReportsList = document.getElementById('copyReportsList'); // Nova referência

    // --- Funções Auxiliares de UI ---

    function addLogMessage(message, level = 'info') {
        const p = document.createElement('p');
        p.textContent = message;
        p.classList.add(`log-${level}`); 
        logMessages.appendChild(p);
        logMessages.scrollTop = logMessages.scrollHeight; 
    }

    function showAlert(message, type = 'info') {
        const alertDiv = document.createElement('div');
        alertDiv.classList.add('alert', `alert-${type}`, 'alert-dismissible', 'fade', 'show');
        alertDiv.setAttribute('role', 'alert');
        alertDiv.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        `;
        dynamicAlerts.appendChild(alertDiv);
        setTimeout(() => {
            if (alertDiv) {
                bootstrap.Alert.getInstance(alertDiv)?.close();
            }
        }, 8000); 
    }

    // --- Socket.IO Event Handlers ---

    socket.on('connect', function() {
        console.log('Conectado ao servidor Socket.IO');
        addLogMessage('Conectado ao servidor.', 'info');
    });

    socket.on('disconnect', function() {
        console.log('Desconectado do servidor Socket.IO');
        addLogMessage('Desconectado do servidor.', 'warning');
    });

    socket.on('status_update', function(data) {
        operationStatus.textContent = data.status_message;
        
        let progress = 0;
        // Lógica para a barra de progresso e números
        if (data.total_files_estimated > 0) {
            progress = (data.files_processed / data.total_files_estimated) * 100;
        } else if (data.running) { 
            // Se a operação está rodando, mas a estimativa ainda é 0 (e.g., início da coleta/varredura)
            // Mostra 0% ou um pequeno valor inicial para indicar que está ativo.
            // Para ser preciso, mostraremos 0% até ter uma estimativa.
            progress = 0; 
        } else { // Se não estiver rodando (ocioso ou finalizado)
            progress = 0;
        }

        progressBar.style.width = progress.toFixed(2) + '%';
        progressBar.setAttribute('aria-valuenow', progress.toFixed(2));
        progressBar.textContent = progress.toFixed(2) + '%';
        
        filesProcessed.textContent = data.files_processed;
        totalFilesEstimated.textContent = data.total_files_estimated;
        currentDirectory.textContent = data.current_directory || 'N/A'; 

        // Gerencia o estado dos botões de controle
        pauseBtn.disabled = !data.running || data.paused;
        resumeBtn.disabled = !data.running || !data.paused;
        stopBtn.disabled = !data.running;

        // Desabilita botões de iniciar operações se já houver uma rodando
        startCollectionBtn.disabled = data.running;
        startComparisonBtn.disabled = data.running;
        startCopyBtn.disabled = data.running; 

        // Atualiza as listas de JSONs a cada status_update
        if (data.all_collected_jsons) {
            updateCollectedJsonsLists(data.all_collected_jsons);
        }
        if (data.all_comparison_jsons) {
            updateComparisonJsonsLists(data.all_comparison_jsons);
        }
        if (data.all_copy_reports) { 
            updateCopyReportsList(data.all_copy_reports);
        }
    });

    socket.on('log_message', function(data) {
        addLogMessage(data.data, data.level);
    });

    socket.on('collection_complete', function(data) {
        showAlert(`Coleta de ${data.type} concluída para ${data.path}! Arquivo: ${data.filename}`, 'success');
        addLogMessage(`Coleta de ${data.type} concluída! Arquivo JSON: ${data.filename}`, 'success');
    });

    socket.on('comparison_complete', function(data) {
        let msg = `Comparação concluída! Relatório JSON: <a href="/results/${data.json_filename}" target="_blank" download>${data.json_filename}</a>`;
        if (data.csv_filename) {
            msg += `<br>Relatório CSV: <a href="/results/${data.csv_filename}" target="_blank" download>${data.csv_filename}</a>`;
        }
        msg += `<br><a href="/report/${data.json_filename}" target="_blank" class="btn btn-sm btn-outline-primary mt-2">Visualizar Relatório Completo</a>`;
        showAlert(msg, 'success');
        addLogMessage('Comparação concluída com sucesso!', 'success');
    });

    socket.on('copy_complete', function(data) {
        let msg = `Operação de cópia finalizada! Copiados: ${data.copied_count}, Falhas: ${data.failed_count}.`;
        if (data.report_json_filename) {
            msg += `<br>Relatório de Cópia: <a href="/copy_report/${data.report_json_filename}" target="_blank" class="btn btn-sm btn-outline-success mt-2"><i class="fas fa-file-alt me-1"></i>Visualizar Relatório</a>`;
        }
        if (data.report_csv_filename) {
             msg += `<a href="/results/${data.report_csv_filename}" target="_blank" download class="btn btn-sm btn-outline-warning mt-2 ms-2"><i class="fas fa-file-csv me-1"></i>Baixar Falhas CSV</a>`;
        }
        showAlert(msg, 'success');
        addLogMessage(`Operação de cópia finalizada! Copiados: ${data.copied_count}, Falhas: ${data.failed_count}.`, 'success');
    });

    socket.on('operation_ended', function() {
        addLogMessage('Operação finalizada ou interrompida. Estado resetado.', 'info');
    });

    // --- Funções para Atualizar Listas de JSONs ---
    function updateCollectedJsonsLists(collectedJsons) {
        jsonOrigemSelect.innerHTML = '<option value="">Selecione um JSON de Origem</option>';
        jsonDestinoSelect.innerHTML = '<option value="">Selecione um JSON de Destino</option>';

        collectedJsons.forEach(jsonFile => {
            if (jsonFile.collection_type === 'origem') {
                const optionOrigem = document.createElement('option');
                optionOrigem.value = jsonFile.filename;
                optionOrigem.textContent = `${jsonFile.filename} (${jsonFile.timestamp} - ${jsonFile.directory_path})`;
                optionOrigem.title = `${jsonFile.directory_path} (Inacessíveis: ${jsonFile.inaccessible_count})`;
                jsonOrigemSelect.appendChild(optionOrigem);
            }
            if (jsonFile.collection_type === 'destino') {
                const optionDestino = document.createElement('option');
                optionDestino.value = jsonFile.filename;
                optionDestino.textContent = `${jsonFile.filename} (${jsonFile.timestamp} - ${jsonFile.directory_path})`;
                optionDestino.title = `${jsonFile.directory_path} (Inacessíveis: ${jsonFile.inaccessible_count})`;
                jsonDestinoSelect.appendChild(optionDestino);
            }
        });

        collectedJsonsList.innerHTML = ''; 
        if (collectedJsons.length === 0) {
            collectedJsonsList.innerHTML = '<li class="list-group-item text-muted">Nenhum JSON de coleta disponível ainda.</li>';
        } else {
            collectedJsons.forEach(jsonFile => {
                const li = document.createElement('li');
                li.classList.add('list-group-item');
                let inaccessibleBadge = jsonFile.inaccessible_count > 0 ? 
                    `<span class="badge bg-warning text-dark ms-2">Inacessíveis: ${jsonFile.inaccessible_count}</span>` : '';
                li.innerHTML = `
                    <a href="/info_data/${jsonFile.filename}" download><i class="fas fa-download me-2"></i>${jsonFile.filename}</a> 
                    (<strong class="text-primary">${jsonFile.collection_type.charAt(0).toUpperCase() + jsonFile.collection_type.slice(1)}</strong>) - ${jsonFile.timestamp} (${jsonFile.directory_path})
                    ${inaccessibleBadge}
                `;
                collectedJsonsList.appendChild(li);
            });
        }
    }

    function updateComparisonJsonsLists(comparisonJsons) {
        comparisonJsonForCopySelect.innerHTML = '<option value="">Selecione um relatório de comparação</option>';
        comparisonJsons.forEach(jsonFile => {
            const option = document.createElement('option');
            option.value = jsonFile.filename;
            option.textContent = `${jsonFile.filename} (${jsonFile.not_copied_count} arquivos não copiados) - ${jsonFile.timestamp}`;
            option.title = `Origem: ${jsonFile.dir_origem} | Destino: ${jsonFile.dir_destino} | Não Copiados: ${jsonFile.not_copied_count}`;
            comparisonJsonForCopySelect.appendChild(option);
        });

        comparisonJsonsList.innerHTML = ''; 
        if (comparisonJsons.length === 0) {
            comparisonJsonsList.innerHTML = '<li class="list-group-item text-muted">Nenhum JSON de comparação disponível ainda.</li>';
        } else {
            comparisonJsons.forEach(jsonFile => {
                const li = document.createElement('li');
                li.classList.add('list-group-item');
                const csvFilename = `not_copied_comparison_${jsonFile.filename.replace('comparison_result_', '').replace('.json', '.csv')}`;
                
                li.innerHTML = `
                    <a href="/report/${jsonFile.filename}" target="_blank" class="btn btn-sm btn-outline-primary me-2"><i class="fas fa-eye me-1"></i>Visualizar</a>
                    <a href="/results/${jsonFile.filename}" download class="btn btn-sm btn-outline-secondary me-2"><i class="fas fa-download me-1"></i>JSON</a>
                    <a href="/results/${csvFilename}" download class="btn btn-sm btn-outline-success"><i class="fas fa-file-csv me-1"></i>CSV</a>
                    <span class="ms-3">(${jsonFile.timestamp} | Não Copiados: <strong>${jsonFile.not_copied_count}</strong>)</span>
                `;
                comparisonJsonsList.appendChild(li);
            });
        }
    }

    function updateCopyReportsList(copyReports) {
        copyReportsList.innerHTML = ''; 
        if (copyReports.length === 0) {
            copyReportsList.innerHTML = '<li class="list-group-item text-muted">Nenhum relatório de cópia disponível ainda.</li>';
        } else {
            copyReports.forEach(report => {
                const li = document.createElement('li');
                li.classList.add('list-group-item');
                const csvFilename = `copy_failed_${report.filename.replace('copy_report_', '').replace('.json', '.csv')}`;
                
                let csvLink = '';
                if (report.files_failed_to_copy > 0) {
                    csvLink = `<a href="/results/${csvFilename}" download class="btn btn-sm btn-outline-warning ms-2"><i class="fas fa-file-csv me-1"></i>Falhas CSV</a>`;
                }

                li.innerHTML = `
                    <a href="/copy_report/${report.filename}" target="_blank" class="btn btn-sm btn-outline-info me-2"><i class="fas fa-eye me-1"></i>Visualizar</a>
                    <a href="/results/${report.filename}" download class="btn btn-sm btn-outline-secondary"><i class="fas fa-download me-1"></i>JSON</a>
                    ${csvLink}
                    <span class="ms-3">(${report.timestamp} | Sucesso: <strong class="text-success">${report.files_copied_successfully}</strong> | Falhas: <strong class="text-danger">${report.files_failed_to_copy}</strong> de ${report.total_files_attempted})</span>
                `;
                copyReportsList.appendChild(li);
            });
        }
    }

    // --- Event Listeners para Formulários e Botões de Controle ---

    document.getElementById('collectionForm').addEventListener('submit', function(event) {
        event.preventDefault(); 
        addLogMessage('Enviando solicitação de coleta...', 'info');
        startCollectionBtn.disabled = true;

        const directoryPath = document.getElementById('directoryPath').value;
        const collectionType = document.getElementById('collectionType').value;

        fetch('/collect', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                directory_path: directoryPath,
                collection_type: collectionType
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                showAlert(data.message, 'info');
            } else {
                showAlert(`Erro ao iniciar coleta: ${data.message}`, 'danger');
                addLogMessage(`Erro do servidor ao iniciar coleta: ${data.message}`, 'error');
                startCollectionBtn.disabled = false;
            }
        })
        .catch(error => {
            console.error('Erro de rede ou na solicitação de coleta:', error);
            showAlert(`Erro de comunicação: ${error.message}`, 'danger');
            addLogMessage(`Erro de rede: ${error.message}`, 'error');
            startCollectionBtn.disabled = false;
        });
    });

    document.getElementById('compareForm').addEventListener('submit', function(event) {
        event.preventDefault();
        addLogMessage('Enviando solicitação de comparação...', 'info');
        startComparisonBtn.disabled = true;

        const jsonOrigem = document.getElementById('jsonOrigem').value;
        const jsonDestino = document.getElementById('jsonDestino').value;

        fetch('/compare', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                json_origem: jsonOrigem,
                json_destino: jsonDestino
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                showAlert(data.message, 'info');
            } else {
                showAlert(`Erro ao iniciar comparação: ${data.message}`, 'danger');
                addLogMessage(`Erro do servidor ao iniciar comparação: ${data.message}`, 'error');
                startComparisonBtn.disabled = false;
            }
        })
        .catch(error => {
            console.error('Erro de rede ou na solicitação de comparação:', error);
            showAlert(`Erro de comunicação: ${error.message}`, 'danger');
            addLogMessage(`Erro de rede: ${error.message}`, 'error');
            startComparisonBtn.disabled = false;
        });
    });

    document.getElementById('copyForm').addEventListener('submit', function(event) {
        event.preventDefault(); 
        addLogMessage('Enviando solicitação de cópia...', 'info');
        startCopyBtn.disabled = true;
        
        const comparisonJson = document.getElementById('comparisonJsonForCopy').value;

        fetch('/copy_missing', { 
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                comparison_json: comparisonJson
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                showAlert(data.message, 'info');
            } else {
                showAlert(`Erro ao iniciar cópia: ${data.message}`, 'danger');
                addLogMessage(`Erro do servidor ao iniciar cópia: ${data.message}`, 'error');
                startCopyBtn.disabled = false; 
            }
        })
        .catch(error => {
            console.error('Erro de rede ou na solicitação de cópia:', error);
            showAlert(`Erro de comunicação: ${error.message}`, 'danger');
            addLogMessage(`Erro de rede: ${error.message}`, 'error');
            startCopyBtn.disabled = false; 
        });
    });

    // Botões de Controle
    pauseBtn.addEventListener('click', function() {
        socket.emit('pause_operation');
        addLogMessage('Solicitando pausa da operação...', 'info');
    });

    resumeBtn.addEventListener('click', function() {
        socket.emit('resume_operation');
        addLogMessage('Solicitando retomada da operação...', 'info');
    });

    stopBtn.addEventListener('click', function() {
        socket.emit('stop_operation');
        addLogMessage('Solicitando interrupção da operação...', 'warning');
    });
});