import os
import json
import csv
from datetime import datetime
import uuid
import threading
import time
import logging

from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_socketio import SocketIO, emit

# --- Configuração da Aplicação ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'sua_chave_secreta_aqui_para_seguranca'
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

# --- Configuração de Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Variáveis Globais de Controle de Operação ---
RESULTS_DIR = 'results'
INFO_DIR = 'info_data' # Novo diretório para os JSONs de coleta
if not os.path.exists(RESULTS_DIR):
    os.makedirs(RESULTS_DIR)
if not os.path.exists(INFO_DIR):
    os.makedirs(INFO_DIR)

operation_state = {
    'running': False,
    'paused': False,
    'stop_requested': False,
    'current_stage': 'idle', # 'collect_origin', 'collect_destination', 'compare'
    'current_directory': '',
    'files_processed': 0,
    'total_files_estimated': 0,
    'status_message': 'Aguardando operação...',
    'last_collected_json': None, # Guarda o nome do último JSON de coleta
    'last_comparison_json': None, # Guarda o nome do JSON de resultado da última comparação
    'last_comparison_csv': None, # Guarda o nome do CSV de resultado da última comparação
    'all_collected_jsons': [] # Lista de todos os JSONs de coleta disponíveis
}
state_lock = threading.Lock()

last_ui_update_time = time.time()
UI_UPDATE_INTERVAL = 0.5 # segundos

# --- Funções Auxiliares ---

def update_and_emit_status(message=None, force_emit=False):
    global last_ui_update_time
    with state_lock:
        if message:
            operation_state['status_message'] = message
        
        current_time = time.time()
        if force_emit or (current_time - last_ui_update_time >= UI_UPDATE_INTERVAL):
            socketio.emit('status_update', operation_state)
            last_ui_update_time = current_time

def log_and_emit_message(level, message, force_emit=False):
    global last_ui_update_time
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    full_message = f"{timestamp} [{level.upper()}] {message}"
    
    if level == 'info':
        logger.info(message)
    elif level == 'warning':
        logger.warning(message)
    elif level == 'error':
        logger.error(message)
    elif level == 'debug':
        logger.debug(message)
    
    current_time = time.time()
    if force_emit or (current_time - last_ui_update_time >= UI_UPDATE_INTERVAL):
        socketio.emit('log_message', {'data': full_message, 'level': level})
        last_ui_update_time = current_time

def check_operation_control():
    with state_lock:
        if operation_state['stop_requested']:
            log_and_emit_message('info', "Sinal de interrupção recebido. Finalizando operação.", force_emit=True)
            return False
        while operation_state['paused']:
            log_and_emit_message('info', f"Operação pausada no diretório: {operation_state['current_directory']}", force_emit=True)
            time.sleep(1)
            if operation_state['stop_requested']:
                log_and_emit_message('info', "Sinal de interrupção recebido durante a pausa. Finalizando operação.", force_emit=True)
                return False
    return True

# --- Funções de Coleta (Reutilizada e Adaptada) ---
def get_file_info_robust(directory, base_dir_to_strip):
    file_info = {}
    total_files_estimate = 0 

    try:
        for root, _, files in os.walk(directory):
            total_files_estimate += len(files)
    except Exception as e:
        log_and_emit_message('error', f"Erro ao estimar arquivos em {directory}: {e}", force_emit=True)
        return None 

    with state_lock:
        operation_state['total_files_estimated'] = total_files_estimate # Resetamos aqui
        operation_state['files_processed'] = 0 # Resetamos aqui
    update_and_emit_status(f"Estimando arquivos em: {directory} (Total estimado: {operation_state['total_files_estimated']})", force_emit=True)


    for root, _, files in os.walk(directory):
        if not check_operation_control():
            return None 

        current_relative_dir = os.path.relpath(root, base_dir_to_strip) if base_dir_to_strip else root
        with state_lock:
            operation_state['current_directory'] = current_relative_dir
        
        update_and_emit_status(f"Processando diretório: {current_relative_dir}", force_emit=True)

        for file_name in files:
            if not check_operation_control():
                return None 

            file_path = os.path.join(root, file_name)
            
            try:
                stat = os.stat(file_path)
                relative_path_in_source = os.path.relpath(file_path, directory)
                
                file_info[relative_path_in_source] = {
                    "size": stat.st_size,
                    "modified_date": datetime.fromtimestamp(stat.st_mtime).isoformat()
                }
                with state_lock:
                    operation_state['files_processed'] += 1
                update_and_emit_status() 

            except FileNotFoundError:
                log_and_emit_message('warning', f"Arquivo não encontrado durante a leitura (pode ter sido movido/excluído): {file_path}")
            except PermissionError:
                log_and_emit_message('warning', f"Permissão negada ao acessar arquivo: {file_path}")
            except Exception as e:
                log_and_emit_message('error', f"Erro inesperado ao processar arquivo {file_path}: {e}", force_emit=True)
    
    return file_info

# --- Tarefas de Coleta e Comparação ---

def perform_collection_task(directory_path, collection_type): # 'origin' or 'destination'
    try:
        with state_lock:
            operation_state['running'] = True
            operation_state['paused'] = False
            operation_state['stop_requested'] = False
            operation_state['current_stage'] = f'collect_{collection_type}'
            operation_state['files_processed'] = 0
            operation_state['total_files_estimated'] = 0
            operation_state['status_message'] = f'Iniciando coleta de {collection_type}...'
            operation_state['last_collected_json'] = None # Reseta o último JSON coletado
            
        update_and_emit_status(f"Coletando informações do diretório de {collection_type}: {directory_path}", force_emit=True)
        log_and_emit_message('info', f"Iniciando coleta de {collection_type}: {directory_path}", force_emit=True)

        collected_info = get_file_info_robust(directory_path, directory_path)
        if collected_info is None:
            log_and_emit_message('info', f"Coleta de {collection_type} abortada ou falhou.", force_emit=True)
            return

        # Salva o JSON da coleta
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_filename = f"info_{collection_type}_{timestamp_str}_{str(uuid.uuid4())[:8]}.json"
        json_filepath = os.path.join(INFO_DIR, json_filename)
        
        collection_data = {
            "timestamp": datetime.now().isoformat(),
            "directory_path": directory_path,
            "collection_type": collection_type,
            "file_info": collected_info
        }

        try:
            with open(json_filepath, 'w', encoding='utf-8') as f:
                json.dump(collection_data, f, indent=4, ensure_ascii=False)
            log_and_emit_message('info', f"JSON de coleta de {collection_type} salvo como: {json_filename}", force_emit=True)
            
            with state_lock:
                operation_state['last_collected_json'] = json_filename
                # Atualiza a lista de JSONs disponíveis (para os selects no frontend)
                operation_state['all_collected_jsons'] = get_available_info_jsons() 
            update_and_emit_status(f"Coleta de {collection_type} concluída. JSON: {json_filename}", force_emit=True)
            socketio.emit('collection_complete', {
                'filename': json_filename, 
                'type': collection_type,
                'path': directory_path
            })

        except IOError as e:
            log_and_emit_message('error', f"Erro ao salvar JSON de coleta {json_filename}: {e}", force_emit=True)

    except Exception as e:
        log_and_emit_message('error', f"Erro crítico durante a coleta: {e}", force_emit=True)
    finally:
        with state_lock:
            operation_state['running'] = False
            operation_state['paused'] = False
            operation_state['stop_requested'] = False
            operation_state['current_stage'] = 'idle'
            operation_state['current_directory'] = ''
            operation_state['files_processed'] = 0
            operation_state['total_files_estimated'] = 0
        update_and_emit_status("Operação de coleta finalizada.", force_emit=True)
        socketio.emit('operation_ended')


def perform_comparison_task_two_jsons(json_origem_filename, json_destino_filename):
    try:
        with state_lock:
            operation_state['running'] = True
            operation_state['paused'] = False
            operation_state['stop_requested'] = False
            operation_state['current_stage'] = 'compare'
            operation_state['files_processed'] = 0 # Reiniciar para a fase de comparação
            operation_state['total_files_estimated'] = 0 # Reiniciar
            operation_state['status_message'] = 'Iniciando comparação entre JSONs...'
            operation_state['last_comparison_json'] = None
            operation_state['last_comparison_csv'] = None
            
        update_and_emit_status(f"Carregando JSONs: {json_origem_filename} e {json_destino_filename}", force_emit=True)
        log_and_emit_message('info', f"Iniciando comparação com JSONs: {json_origem_filename} e {json_destino_filename}", force_emit=True)

        origem_filepath = os.path.join(INFO_DIR, json_origem_filename)
        destino_filepath = os.path.join(INFO_DIR, json_destino_filename)

        origem_data = {}
        destino_data = {}
        dir_origem_path = "N/A"
        dir_destino_path = "N/A"

        try:
            with open(origem_filepath, 'r', encoding='utf-8') as f:
                origem_full_data = json.load(f)
                origem_info = origem_full_data.get('file_info', {})
                dir_origem_path = origem_full_data.get('directory_path', "N/A")
            log_and_emit_message('info', f"JSON de origem '{json_origem_filename}' carregado.", force_emit=True)
        except Exception as e:
            log_and_emit_message('error', f"Erro ao carregar JSON de origem '{json_origem_filename}': {e}", force_emit=True)
            return

        try:
            with open(destino_filepath, 'r', encoding='utf-8') as f:
                destino_full_data = json.load(f)
                destino_info = destino_full_data.get('file_info', {})
                dir_destino_path = destino_full_data.get('directory_path', "N/A")
            log_and_emit_message('info', f"JSON de destino '{json_destino_filename}' carregado.", force_emit=True)
        except Exception as e:
            log_and_emit_message('error', f"Erro ao carregar JSON de destino '{json_destino_filename}': {e}", force_emit=True)
            return

        log_and_emit_message('info', "JSONs carregados. Identificando arquivos não copiados...", force_emit=True)
        update_and_emit_status("Identificando arquivos não copiados...", force_emit=True)

        not_copied_files_details = []
        with state_lock:
            operation_state['total_files_estimated'] = len(origem_info) # Estima arquivos a comparar
        
        processed_count = 0
        for file_path_rel, info_origem in origem_info.items():
            if not check_operation_control():
                log_and_emit_message('info', "Interrupção detectada durante a identificação de arquivos não copiados.", force_emit=True)
                return

            if file_path_rel not in destino_info:
                # O caminho completo esperado no destino é inferido a partir do caminho do JSON de destino
                # O ideal seria que o JSON de destino também armazenasse o base_dir para reconstruir o path
                # Por simplicidade, vamos usar o dir_destino_path do JSON de destino
                full_expected_path_in_destination = os.path.join(dir_destino_path, file_path_rel)
                not_copied_files_details.append({
                    "relative_path": file_path_rel,
                    "expected_destination_path": full_expected_path_in_destination,
                    "source_size": info_origem.get("size"),
                    "source_modified_date": info_origem.get("modified_date")
                })
            
            processed_count += 1
            with state_lock:
                operation_state['files_processed'] = processed_count
            update_and_emit_status() # Atualiza o progresso da comparação

        # Gera o JSON de resultados da comparação
        comparison_session_id = str(uuid.uuid4())
        comparison_json_filename = f"comparison_result_{comparison_session_id}.json"
        comparison_json_filepath = os.path.join(RESULTS_DIR, comparison_json_filename)

        result_data = {
            "timestamp": datetime.now().isoformat(),
            "json_origem_used": json_origem_filename,
            "json_destino_used": json_destino_filename,
            "dir_origem": dir_origem_path,
            "dir_destino": dir_destino_path,
            "not_copied_files_details": not_copied_files_details
        }
        
        try:
            with open(comparison_json_filepath, 'w', encoding='utf-8') as f:
                json.dump(result_data, f, indent=4, ensure_ascii=False)
            log_and_emit_message('info', f"JSON de resultados da comparação salvo como: {comparison_json_filename}", force_emit=True)
            with state_lock:
                operation_state['last_comparison_json'] = comparison_json_filename
        except IOError as e:
            log_and_emit_message('error', f"Erro ao salvar JSON de comparação {comparison_json_filename}: {e}", force_emit=True)

        # Gera o CSV de resultados da comparação
        comparison_csv_filename = f"not_copied_comparison_{comparison_session_id}.csv"
        comparison_csv_filepath = os.path.join(RESULTS_DIR, comparison_csv_filename)
        if not_copied_files_details:
            try:
                with open(comparison_csv_filepath, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(["Caminho Relativo do Arquivo", "Caminho Completo Esperado no Destino", "Tamanho Origem", "Data Modificação Origem"])
                    for file_detail in not_copied_files_details:
                        writer.writerow([
                            file_detail["relative_path"],
                            file_detail["expected_destination_path"],
                            file_detail["source_size"],
                            file_detail["source_modified_date"]
                        ])
                log_and_emit_message('info', f"CSV de arquivos não copiados salvo como: {comparison_csv_filename}", force_emit=True)
                with state_lock:
                    operation_state['last_comparison_csv'] = comparison_csv_filename
            except IOError as e:
                log_and_emit_message('error', f"Erro ao salvar CSV de comparação {comparison_csv_filename}: {e}", force_emit=True)
        else:
            log_and_emit_message('info', "Nenhum arquivo não copiado encontrado. Nenhum CSV de comparação gerado.", force_emit=True)
            with state_lock:
                operation_state['last_comparison_csv'] = None

        log_and_emit_message('info', "Comparação concluída com sucesso!", force_emit=True)
        socketio.emit('comparison_complete', {
            'json_filename': operation_state['last_comparison_json'], 
            'csv_filename': operation_state['last_comparison_csv']
        })

    except Exception as e:
        log_and_emit_message('error', f"Erro crítico durante a comparação: {e}", force_emit=True)
    finally:
        with state_lock:
            operation_state['running'] = False
            operation_state['paused'] = False
            operation_state['stop_requested'] = False
            operation_state['current_stage'] = 'idle'
            operation_state['current_directory'] = ''
            operation_state['files_processed'] = 0
            operation_state['total_files_estimated'] = 0
        update_and_emit_status("Operação de comparação finalizada.", force_emit=True)
        socketio.emit('operation_ended')

# Função para listar os JSONs de info_data disponíveis
def get_available_info_jsons():
    jsons = []
    for filename in os.listdir(INFO_DIR):
        if filename.endswith('.json'):
            filepath = os.path.join(INFO_DIR, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    dir_path = data.get('directory_path', 'N/A')
                    collection_type = data.get('collection_type', 'N/A')
                    timestamp = data.get('timestamp', 'N/A')
                    jsons.append({
                        'filename': filename,
                        'directory_path': dir_path,
                        'collection_type': collection_type,
                        'timestamp': timestamp
                    })
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Não foi possível ler ou decodificar JSON: {filename} - {e}")
                continue
    # Ordenar por timestamp, mais recente primeiro
    jsons.sort(key=lambda x: x['timestamp'], reverse=True)
    return jsons

# --- Rotas da Aplicação Web ---

@app.route('/', methods=['GET'])
def index():
    # Ao carregar a página, lista os JSONs de coleta disponíveis
    with state_lock:
        operation_state['all_collected_jsons'] = get_available_info_jsons()
    return render_template('index.html', 
                           collected_jsons=operation_state['all_collected_jsons'])

@app.route('/collect', methods=['POST'])
def collect_data():
    directory_path = request.form['directory_path']
    collection_type = request.form['collection_type'] # 'origin' or 'destination'

    if not os.path.isdir(directory_path):
        with state_lock:
            operation_state['status_message'] = f"Diretório inválido ou não acessível: {directory_path}"
        return render_template('index.html', error_message=f"Diretório inválido ou não acessível: {directory_path}", 
                               collected_jsons=get_available_info_jsons())

    with state_lock:
        if operation_state['running']:
            operation_state['status_message'] = "Uma operação já está em andamento. Aguarde ou interrompa."
            return render_template('index.html', error_message="Uma operação já está em andamento. Aguarde ou interrompa.",
                                   collected_jsons=get_available_info_jsons())
    
    thread = threading.Thread(target=perform_collection_task, args=(directory_path, collection_type))
    thread.start()

    return render_template('index.html', 
                           operation_started=True, 
                           collected_jsons=get_available_info_jsons()) # Passa a lista atualizada

@app.route('/compare', methods=['POST'])
def compare_data():
    json_origem_filename = request.form['json_origem_filename']
    json_destino_filename = request.form['json_destino_filename']

    # Valida se os arquivos existem no diretório INFO_DIR
    origem_filepath = os.path.join(INFO_DIR, json_origem_filename)
    destino_filepath = os.path.join(INFO_DIR, json_destino_filename)

    if not os.path.exists(origem_filepath) or not os.path.exists(destino_filepath):
        with state_lock:
            operation_state['status_message'] = "Um ou ambos os arquivos JSON selecionados não foram encontrados."
        return render_template('index.html', error_message="Um ou ambos os arquivos JSON selecionados não foram encontrados.",
                               collected_jsons=get_available_info_jsons())

    with state_lock:
        if operation_state['running']:
            operation_state['status_message'] = "Uma operação já está em andamento. Aguarde ou interrompa."
            return render_template('index.html', error_message="Uma operação já está em andamento. Aguarde ou interrompa.",
                                   collected_jsons=get_available_info_jsons())
    
    thread = threading.Thread(target=perform_comparison_task_two_jsons, args=(json_origem_filename, json_destino_filename))
    thread.start()

    return render_template('index.html', 
                           operation_started=True, 
                           collected_jsons=get_available_info_jsons()) # Passa a lista atualizada

@app.route('/results/<filename>')
def download_file(filename):
    # Verifica se o arquivo está no RESULTS_DIR ou INFO_DIR
    if os.path.exists(os.path.join(RESULTS_DIR, filename)):
        return send_from_directory(RESULTS_DIR, filename, as_attachment=True)
    elif os.path.exists(os.path.join(INFO_DIR, filename)):
        return send_from_directory(INFO_DIR, filename, as_attachment=True)
    else:
        return "Arquivo não encontrado.", 404

@app.route('/report/<json_filename>')
def report(json_filename):
    json_filepath = os.path.join(RESULTS_DIR, json_filename)
    if not os.path.exists(json_filepath):
        return "Relatório não encontrado ou arquivo JSON excluído.", 404

    try:
        with open(json_filepath, 'r', encoding='utf-8') as f:
            result_data = json.load(f)
        
        not_copied_files_details = result_data.get("not_copied_files_details", [])
        dir_origem = result_data.get("dir_origem", "N/A")
        dir_destino = result_data.get("dir_destino", "N/A")
        timestamp = result_data.get("timestamp", "N/A")

        csv_filename_for_report = f"not_copied_comparison_{json_filename.replace('comparison_result_', '').replace('.json', '.csv')}"
        csv_filepath_for_join = os.path.join(RESULTS_DIR, csv_filename_for_report)
        csv_available = os.path.exists(csv_filepath_for_join)

        return render_template('report.html', 
                               not_copied_files_details=not_copied_files_details,
                               dir_origem=dir_origem,
                               dir_destino=dir_destino,
                               timestamp=timestamp,
                               csv_filename=csv_filename_for_report if csv_available else None)
    except json.JSONDecodeError:
        return "Erro ao carregar o arquivo JSON do relatório. Formato inválido.", 500
    except Exception as e:
        logger.error(f"Erro ao gerar relatório de {json_filename}: {e}")
        return "Ocorreu um erro ao gerar o relatório.", 500

# --- SocketIO Events (Controle do Servidor) ---

@socketio.on('connect')
def handle_connect():
    log_and_emit_message('info', 'Cliente conectado ao SocketIO.', force_emit=True)
    with state_lock:
        operation_state['all_collected_jsons'] = get_available_info_jsons() # Atualiza a lista para o cliente
    update_and_emit_status(force_emit=True) # Envia o status atual da operação

@socketio.on('disconnect')
def handle_disconnect():
    log_and_emit_message('info', 'Cliente desconectado do SocketIO.', force_emit=True)

@socketio.on('pause_operation')
def handle_pause_request():
    with state_lock:
        if operation_state['running'] and not operation_state['paused']:
            operation_state['paused'] = True
            log_and_emit_message('info', "Solicitação de PAUSA recebida. Operação será pausada.", force_emit=True)
            update_and_emit_status("Operação pausada.", force_emit=True)
        elif operation_state['paused']:
            log_and_emit_message('warning', "Operação já está pausada.", force_emit=True)
            update_and_emit_status("Operação já está pausada.", force_emit=True)

@socketio.on('resume_operation')
def handle_resume_request():
    with state_lock:
        if operation_state['running'] and operation_state['paused']:
            operation_state['paused'] = False
            log_and_emit_message('info', "Solicitação de RESUMO recebida. Operação será retomada.", force_emit=True)
            update_and_emit_status("Operação em andamento.", force_emit=True)
        elif not operation_state['paused']:
            log_and_emit_message('warning', "Operação não está pausada.", force_emit=True)
            update_and_emit_status("Operação não está pausada.", force_emit=True)

@socketio.on('stop_operation')
def handle_stop_request():
    with state_lock:
        if operation_state['running']:
            operation_state['stop_requested'] = True
            operation_state['paused'] = False
            log_and_emit_message('info', "Solicitação de INTERRUPÇÃO recebida. A operação será finalizada em breve.", force_emit=True)
            update_and_emit_status("Solicitando interrupção...", force_emit=True)
        else:
            log_and_emit_message('warning', "Nenhuma operação em andamento para interromper.", force_emit=True)
            update_and_emit_status("Nenhuma operação em andamento.", force_emit=True)

@app.route('/status')
def get_current_status():
    with state_lock:
        return jsonify(operation_state)

if __name__ == '__main__':
    socketio.run(app, debug=True, allow_unsafe_werkzeug=True, port=5001)
