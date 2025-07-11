import os
import json
import threading
import time
import uuid
import shutil
import csv
from datetime import datetime
from collections import defaultdict
from flask import Flask, render_template, request, jsonify, send_from_directory, url_for
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename
import logging

# Configuração básica de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
# Aumentar o limite de tempo limite para evitar disconexões durante operações longas
app.config['SECRET_KEY'] = 'your_secret_key' # Mude para uma chave secreta forte em produção
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', ping_interval=30, ping_timeout=60) # Ajuste ping_timeout

# Diretórios para os arquivos
INFO_DIR = 'info_data'
RESULTS_DIR = 'results'

# Garante que os diretórios existam
if not os.path.exists(INFO_DIR):
    os.makedirs(INFO_DIR)
if not os.path.exists(RESULTS_DIR):
    os.makedirs(RESULTS_DIR)

# Estado global da operação
# Usamos um dicionário para manter o estado e um Lock para acesso thread-safe
state_lock = threading.Lock()
initial_operation_state = {
    'running': False,
    'paused': False,
    'current_stage': 'idle', # idle, collecting, comparing, copying
    'status_message': 'Aguardando operação...',
    'files_processed': 0,
    'total_files_estimated': 0,
    'current_directory': 'N/A',
    'all_collected_jsons': [],
    'all_comparison_jsons': [],
    'all_copy_reports': [] # Nova lista para relatórios de cópia
}
operation_state = initial_operation_state.copy()

# Variáveis de controle para pausar/parar
stop_event = threading.Event()
pause_event = threading.Event()

# --- Funções Auxiliares de Gerenciamento de Estado e Log ---

def log_and_emit_message(level, message, force_emit=False):
    """Loga a mensagem e a emite via SocketIO."""
    getattr(logger, level)(message) # Usa o nível de log correspondente
    socketio.emit('log_message', {'level': level, 'data': message}, namespace='/')
    if force_emit:
        socketio.sleep(0.01) # Pequeno sleep para garantir que a mensagem seja enviada

def update_and_emit_status(message=None, force_emit=False):
    """Atualiza o status e emite para o frontend."""
    with state_lock:
        if message:
            operation_state['status_message'] = message
        # Sempre garantimos que as listas de JSONs estejam atualizadas no estado
        operation_state['all_collected_jsons'] = get_available_info_jsons()
        operation_state['all_comparison_jsons'] = get_available_comparison_jsons()
        operation_state['all_copy_reports'] = get_available_copy_reports()

        current_state = operation_state.copy()
    
    socketio.emit('status_update', current_state, namespace='/')
    if force_emit:
        socketio.sleep(0.01) # Pequeno sleep para garantir que a atualização seja enviada

def check_operation_control():
    """Verifica se a operação foi pausada ou parada."""
    while pause_event.is_set():
        if stop_event.is_set():
            return False # Se parar durante a pausa, interrompe
        socketio.sleep(0.1) # Espera enquanto estiver pausado
    return not stop_event.is_set() # Retorna True se não houver pedido de parada

# --- Funções para Obter JSONs Disponíveis ---

def get_available_info_jsons():
    """Retorna uma lista de dicionários com informações dos JSONs de coleta disponíveis."""
    jsons_info = []
    for filename in os.listdir(INFO_DIR):
        if filename.startswith('collected_info_') and filename.endswith('.json'):
            filepath = os.path.join(INFO_DIR, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Verifica se as chaves existem para evitar KeyError
                    collection_type = data.get('collection_type', 'unknown')
                    timestamp_raw = data.get('timestamp', 'N/A')
                    directory_path = data.get('base_directory', 'N/A')
                    inaccessible_count = data.get('inaccessible_files_count', 0)

                    # Formata o timestamp se for válido
                    try:
                        timestamp_formatted = datetime.fromisoformat(timestamp_raw).strftime("%d/%m/%Y %H:%M:%S")
                    except ValueError:
                        timestamp_formatted = timestamp_raw
                    
                    jsons_info.append({
                        'filename': filename,
                        'collection_type': collection_type,
                        'timestamp': timestamp_formatted,
                        'directory_path': directory_path,
                        'inaccessible_count': inaccessible_count
                    })
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Não foi possível ler ou decodificar JSON de coleta: {filename} - {e}")
                continue
    # Ordena os JSONs por timestamp, do mais recente para o mais antigo
    jsons_info.sort(key=lambda x: x['timestamp'], reverse=True)
    return jsons_info

def get_available_comparison_jsons():
    """Retorna uma lista de dicionários com informações dos JSONs de comparação disponíveis."""
    jsons_info = []
    for filename in os.listdir(RESULTS_DIR):
        if filename.startswith('comparison_result_') and filename.endswith('.json'):
            filepath = os.path.join(RESULTS_DIR, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    timestamp_raw = data.get('timestamp', 'N/A')
                    try:
                        timestamp_formatted = datetime.fromisoformat(timestamp_raw).strftime("%d/%m/%Y %H:%M:%S")
                    except ValueError:
                        timestamp_formatted = timestamp_raw
                    
                    not_copied_count = len(data.get('not_copied_files_details', []))
                    
                    jsons_info.append({
                        'filename': filename,
                        'timestamp': timestamp_formatted,
                        'dir_origem': data.get('dir_origem', 'N/A'),
                        'dir_destino': data.get('dir_destino', 'N/A'),
                        'not_copied_count': not_copied_count
                    })
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Não foi possível ler ou decodificar JSON de comparação: {filename} - {e}")
                continue
    jsons_info.sort(key=lambda x: x['timestamp'], reverse=True)
    return jsons_info

def get_available_copy_reports():
    """Retorna uma lista de dicionários com informações dos JSONs de relatório de cópia disponíveis."""
    reports = []
    for filename in os.listdir(RESULTS_DIR):
        if filename.startswith('copy_report_') and filename.endswith('.json'):
            filepath = os.path.join(RESULTS_DIR, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    timestamp_raw = data.get('timestamp', 'N/A')
                    try:
                        timestamp_formatted = datetime.fromisoformat(timestamp_raw).strftime("%d/%m/%Y %H:%M:%S")
                    except ValueError:
                        timestamp_formatted = timestamp_raw
                    
                    reports.append({
                        'filename': filename,
                        'timestamp': timestamp_formatted,
                        'source_base_directory': data.get('source_base_directory', 'N/A'),
                        'destination_base_directory': data.get('destination_base_directory', 'N/A'),
                        'total_files_attempted': data.get('total_files_attempted', 0),
                        'files_copied_successfully': data.get('files_copied_successfully', 0),
                        'files_failed_to_copy': data.get('files_failed_to_copy', 0)
                    })
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Não foi possível ler ou decodificar JSON de relatório de cópia: {filename} - {e}")
                continue
    reports.sort(key=lambda x: x['timestamp'], reverse=True)
    return reports

# --- Funções de Operação (Coleta, Comparação, Cópia) ---

def get_file_info_robust(base_path):
    """
    Coleta informações de arquivos em um diretório de forma robusta,
    tratando erros de acesso e coletando metadados.
    """
    file_info = {}
    inaccessible_files = []
    
    # Pré-contagem de arquivos para a barra de progresso
    total_files_to_scan = 0
    for root, _, files in os.walk(base_path, followlinks=False): # followlinks=False para evitar loops em links simbólicos
        total_files_to_scan += len(files)
    
    with state_lock:
        operation_state['total_files_estimated'] = total_files_to_scan
        operation_state['files_processed'] = 0

    log_and_emit_message('info', f"Iniciando varredura em '{base_path}' ({total_files_to_scan} arquivos estimados)...", force_emit=True)

    for root, _, files in os.walk(base_path, followlinks=False):
        if not check_operation_control():
            log_and_emit_message('info', "Interrupção detectada durante a coleta de arquivos.", force_emit=True)
            break
        
        with state_lock:
            # Garante que o current_directory seja o path relativo à base_path
            relative_root = os.path.relpath(root, base_path)
            operation_state['current_directory'] = relative_root if relative_root != '.' else '/'
        update_and_emit_status()

        for file in files:
            if not check_operation_control():
                break

            file_path = os.path.join(root, file)
            relative_path = os.path.relpath(file_path, base_path)
            
            try:
                stat_info = os.stat(file_path)
                file_info[relative_path] = {
                    'size': stat_info.st_size,
                    'mtime': stat_info.st_mtime, # Data da última modificação
                    'md5': None # MD5 pode ser adicionado aqui se necessário, mas é custoso para performance
                }
            except FileNotFoundError:
                inaccessible_files.append({'path': relative_path, 'reason': 'Arquivo não encontrado durante a varredura.'})
                log_and_emit_message('warning', f"Arquivo não encontrado durante varredura: {file_path}", force_emit=True)
            except PermissionError:
                inaccessible_files.append({'path': relative_path, 'reason': 'Permissão negada.'})
                log_and_emit_message('error', f"Permissão negada ao acessar: {file_path}", force_emit=True)
            except Exception as e:
                inaccessible_files.append({'path': relative_path, 'reason': f'Erro inesperado: {str(e)}'})
                log_and_emit_message('error', f"Erro ao acessar {file_path}: {e}", force_emit=True)

            with state_lock:
                operation_state['files_processed'] += 1
            update_and_emit_status()
    
    log_and_emit_message('info', f"Varredura em '{base_path}' concluída.", force_emit=True)
    return file_info, inaccessible_files

def perform_collection_task(directory_path, collection_type):
    """Executa a tarefa de coleta em uma thread separada."""
    try:
        with state_lock:
            global operation_state
            operation_state = initial_operation_state.copy() # Reseta o estado
            operation_state['running'] = True
            operation_state['current_stage'] = 'collecting'
            operation_state['status_message'] = f"Iniciando coleta de {collection_type} em: {directory_path}"
        
        update_and_emit_status(force_emit=True)
        log_and_emit_message('info', f"Coleta de '{collection_type}' iniciada para: {directory_path}", force_emit=True)

        if not os.path.isdir(directory_path):
            log_and_emit_message('error', f"Diretório '{directory_path}' não é válido ou acessível.", force_emit=True)
            socketio.emit('collection_complete', {'status': 'error', 'message': 'Diretório inválido.'})
            return

        file_info, inaccessible_files = get_file_info_robust(directory_path)

        session_id = str(uuid.uuid4())
        filename = f"collected_info_{collection_type}_{session_id}.json"
        filepath = os.path.join(INFO_DIR, filename)

        report_data = {
            "session_id": session_id,
            "collection_type": collection_type,
            "base_directory": directory_path,
            "timestamp": datetime.now().isoformat(),
            "total_files_scanned": len(file_info),
            "inaccessible_files_count": len(inaccessible_files),
            "inaccessible_files_details": inaccessible_files,
            "files": file_info
        }

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=4, ensure_ascii=False)
            log_and_emit_message('success', f"Coleta concluída! Relatório salvo como: {filename}", force_emit=True)
            socketio.emit('collection_complete', {
                'status': 'success',
                'type': collection_type,
                'path': directory_path,
                'filename': filename
            })
        except IOError as e:
            log_and_emit_message('error', f"Erro ao salvar o arquivo JSON: {e}", force_emit=True)
            socketio.emit('collection_complete', {'status': 'error', 'message': f'Erro ao salvar arquivo: {e}'})

    except Exception as e:
        log_and_emit_message('error', f"Erro crítico durante a coleta: {e}", force_emit=True)
        socketio.emit('collection_complete', {'status': 'error', 'message': f'Erro inesperado: {e}'})
    finally:
        with state_lock:
            operation_state = initial_operation_state.copy() # Reseta o estado
            operation_state['all_collected_jsons'] = get_available_info_jsons() # Atualiza as listas
            operation_state['all_comparison_jsons'] = get_available_comparison_jsons()
            operation_state['all_copy_reports'] = get_available_copy_reports()
        update_and_emit_status("Operação de coleta finalizada.", force_emit=True)
        socketio.emit('operation_ended')

def perform_comparison_task(json_origem_filename, json_destino_filename):
    """Executa a tarefa de comparação em uma thread separada."""
    try:
        with state_lock:
            global operation_state
            operation_state = initial_operation_state.copy()
            operation_state['running'] = True
            operation_state['current_stage'] = 'comparing'
        
        update_and_emit_status(f"Carregando dados para comparação...", force_emit=True)
        log_and_emit_message('info', f"Iniciando comparação entre '{json_origem_filename}' e '{json_destino_filename}'", force_emit=True)

        path_origem = os.path.join(INFO_DIR, secure_filename(json_origem_filename))
        path_destino = os.path.join(INFO_DIR, secure_filename(json_destino_filename))

        data_origem = {}
        data_destino = {}

        try:
            with open(path_origem, 'r', encoding='utf-8') as f:
                data_origem = json.load(f)
            with open(path_destino, 'r', encoding='utf-8') as f:
                data_destino = json.load(f)
            log_and_emit_message('info', "Dados de origem e destino carregados com sucesso.", force_emit=True)
        except Exception as e:
            log_and_emit_message('error', f"Erro ao carregar arquivos JSON para comparação: {e}", force_emit=True)
            return

        files_origem = data_origem.get('files', {})
        files_destino = data_destino.get('files', {})
        dir_origem = data_origem.get('base_directory', 'Desconhecido')
        dir_destino = data_destino.get('base_directory', 'Desconhecido')

        missing_in_destino = []
        different_files = []
        found_in_both = []

        total_files_origem = len(files_origem)
        with state_lock:
            operation_state['total_files_estimated'] = total_files_origem
            operation_state['files_processed'] = 0
        update_and_emit_status("Comparando arquivos...", force_emit=True)

        for i, (path, info_origem) in enumerate(files_origem.items()):
            if not check_operation_control():
                log_and_emit_message('info', "Interrupção detectada durante a comparação de arquivos.", force_emit=True)
                break
            
            with state_lock:
                operation_state['files_processed'] = i + 1
                operation_state['current_directory'] = os.path.dirname(path) if os.path.dirname(path) else '/'
            update_and_emit_status()

            if path not in files_destino:
                missing_in_destino.append({
                    'relative_path': path,
                    'status': 'Não encontrado no destino',
                    'size_origem': info_origem.get('size'),
                    'mtime_origem': datetime.fromtimestamp(info_origem.get('mtime', 0)).isoformat() if info_origem.get('mtime') else None
                })
            else:
                info_destino = files_destino[path]
                if info_origem.get('size') != info_destino.get('size') or \
                   info_origem.get('mtime') != info_destino.get('mtime'): # Apenas mtime, MD5 é custoso
                    different_files.append({
                        'relative_path': path,
                        'status': 'Tamanho ou data de modificação diferente',
                        'size_origem': info_origem.get('size'),
                        'mtime_origem': datetime.fromtimestamp(info_origem.get('mtime', 0)).isoformat() if info_origem.get('mtime') else None,
                        'size_destino': info_destino.get('size'),
                        'mtime_destino': datetime.fromtimestamp(info_destino.get('mtime', 0)).isoformat() if info_destino.get('mtime') else None
                    })
                else:
                    found_in_both.append(path)

        session_id = str(uuid.uuid4())
        json_filename = f"comparison_result_{session_id}.json"
        json_filepath = os.path.join(RESULTS_DIR, json_filename)
        csv_filename = f"not_copied_comparison_{session_id}.csv"
        csv_filepath = os.path.join(RESULTS_DIR, csv_filename)

        all_not_copied = missing_in_destino + different_files

        comparison_result = {
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(),
            "json_origem_filename": json_origem_filename,
            "json_destino_filename": json_destino_filename,
            "dir_origem": dir_origem,
            "dir_destino": dir_destino,
            "total_files_origem": total_files_origem,
            "total_files_destino": len(files_destino),
            "files_found_in_both": len(found_in_both),
            "files_missing_in_destino": len(missing_in_destino),
            "files_different": len(different_files),
            "not_copied_files_count": len(all_not_copied),
            "not_copied_files_details": all_not_copied,
            "summary_by_type": {
                "origem_missing_in_destino": len(missing_in_destino),
                "origem_different_in_destino": len(different_files)
            }
        }

        try:
            with open(json_filepath, 'w', encoding='utf-8') as f:
                json.dump(comparison_result, f, indent=4, ensure_ascii=False)
            log_and_emit_message('success', f"Comparação concluída! Relatório JSON salvo como: {json_filename}", force_emit=True)

            # Salva também um CSV dos arquivos não copiados
            if all_not_copied:
                with open(csv_filepath, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(["Caminho Relativo", "Status", "Tamanho Origem", "Data Mod. Origem", "Tamanho Destino", "Data Mod. Destino"])
                    for item in all_not_copied:
                        writer.writerow([
                            item.get('relative_path', 'N/A'),
                            item.get('status', 'N/A'),
                            item.get('size_origem', 'N/A'),
                            item.get('mtime_origem', 'N/A'),
                            item.get('size_destino', 'N/A'),
                            item.get('mtime_destino', 'N/A')
                        ])
                log_and_emit_message('info', f"CSV de arquivos não copiados salvo como: {csv_filename}", force_emit=True)
            else:
                log_and_emit_message('info', "Todos os arquivos foram encontrados ou são idênticos. Nenhum CSV de não copiados gerado.", force_emit=True)


            socketio.emit('comparison_complete', {
                'status': 'success',
                'json_filename': json_filename,
                'csv_filename': csv_filename if all_not_copied else None
            })

        except IOError as e:
            log_and_emit_message('error', f"Erro ao salvar arquivo de comparação JSON ou CSV: {e}", force_emit=True)
            socketio.emit('comparison_complete', {'status': 'error', 'message': f'Erro ao salvar arquivo: {e}'})

    except Exception as e:
        log_and_emit_message('error', f"Erro crítico durante a comparação: {e}", force_emit=True)
        socketio.emit('comparison_complete', {'status': 'error', 'message': f'Erro inesperado: {e}'})
    finally:
        with state_lock:
            operation_state = initial_operation_state.copy()
            operation_state['all_collected_jsons'] = get_available_info_jsons()
            operation_state['all_comparison_jsons'] = get_available_comparison_jsons()
            operation_state['all_copy_reports'] = get_available_copy_reports()
        update_and_emit_status("Operação de comparação finalizada.", force_emit=True)
        socketio.emit('operation_ended')

def perform_copy_task(comparison_json_filename):
    """
    Executa a tarefa de cópia de arquivos ausentes em uma thread separada.
    Gera um relatório de sucesso/falha da cópia.
    """
    try:
        with state_lock:
            global operation_state
            operation_state = initial_operation_state.copy()
            operation_state['running'] = True
            operation_state['current_stage'] = 'copy_files'
            
        update_and_emit_status(f"Carregando relatório de comparação: {comparison_json_filename}", force_emit=True)
        log_and_emit_message('info', f"Iniciando cópia com base em: {comparison_json_filename}", force_emit=True)

        comparison_filepath = os.path.join(RESULTS_DIR, secure_filename(comparison_json_filename))
        
        comparison_data = {}
        try:
            with open(comparison_filepath, 'r', encoding='utf-8') as f:
                comparison_data = json.load(f)
            log_and_emit_message('info', f"Relatório de comparação '{comparison_json_filename}' carregado.", force_emit=True)
        except Exception as e:
            log_and_emit_message('error', f"Erro ao carregar relatório de comparação '{comparison_json_filename}': {e}", force_emit=True)
            return

        not_copied_files = comparison_data.get('not_copied_files_details', [])
        source_base_dir = comparison_data.get('dir_origem')
        destination_base_dir = comparison_data.get('dir_destino')

        if not source_base_dir or not destination_base_dir:
            log_and_emit_message('error', "Caminhos de origem ou destino não encontrados no relatório de comparação.", force_emit=True)
            return
        
        if not os.path.isdir(source_base_dir):
            log_and_emit_message('error', f"Diretório de origem '{source_base_dir}' do relatório não é válido ou acessível.", force_emit=True)
            return

        if not os.path.isdir(destination_base_dir):
            log_and_emit_message('error', f"Diretório de destino '{destination_base_dir}' do relatório não é válido ou acessível.", force_emit=True)
            return

        # Filtra apenas os arquivos que 'Não encontrado no destino' para cópia.
        # Ajustado para considerar também "Tamanho ou data de modificação diferente" para cópia
        files_to_copy = [
            f for f in not_copied_files 
            if f['status'] == 'Não encontrado no destino' or f['status'] == 'Tamanho ou data de modificação diferente'
        ]

        with state_lock:
            operation_state['total_files_estimated'] = len(files_to_copy)
            operation_state['files_processed'] = 0
        log_and_emit_message('info', f"Total de arquivos a tentar copiar: {operation_state['total_files_estimated']}", force_emit=True)
        update_and_emit_status("Iniciando cópia dos arquivos...", force_emit=True)

        copied_success = []
        copied_failed = []

        for file_detail in files_to_copy:
            if not check_operation_control(): 
                log_and_emit_message('info', "Interrupção detectada durante a cópia de arquivos.", force_emit=True)
                break

            relative_path = file_detail['relative_path']
            source_file_path = os.path.join(source_base_dir, relative_path)
            destination_file_path = os.path.join(destination_base_dir, relative_path)
            
            # Garante que o diretório de destino exista
            os.makedirs(os.path.dirname(destination_file_path), exist_ok=True)

            with state_lock:
                operation_state['current_directory'] = os.path.dirname(relative_path) if os.path.dirname(relative_path) else '/'
            update_and_emit_status(f"Copiando: {relative_path}", force_emit=True)

            copy_status = "Sucesso"
            error_message = ""
            try:
                shutil.copy2(source_file_path, destination_file_path) # Copia dados e metadados
                copied_success.append({
                    'relative_path': relative_path,
                    'source_path': source_file_path,
                    'destination_path': destination_file_path,
                    'status': 'Copiado com sucesso',
                    'timestamp': datetime.now().isoformat()
                })
                log_and_emit_message('debug', f"Copiado: {source_file_path} para {destination_file_path}")
            except FileNotFoundError:
                copy_status = "Falha: Arquivo de origem não encontrado"
                error_message = f"Origem não encontrada: {source_file_path}"
                log_and_emit_message('warning', f"Falha na cópia: {error_message}", force_emit=True)
            except PermissionError:
                copy_status = "Falha: Permissão negada"
                error_message = f"Permissão negada ao copiar {source_file_path} para {destination_file_path}"
                log_and_emit_message('error', f"Falha na cópia: {error_message}", force_emit=True)
            except shutil.SameFileError:
                copy_status = "Falha: Arquivos são o mesmo"
                error_message = f"Origem e destino são o mesmo arquivo: {source_file_path}"
                log_and_emit_message('warning', f"Falha na cópia: {error_message}", force_emit=True)
            except Exception as e:
                copy_status = "Falha: Erro inesperado"
                error_message = f"Erro inesperado: {str(e)}"
                log_and_emit_message('error', f"Falha inesperada na cópia de {source_file_path}: {e}", force_emit=True)
            
            if copy_status.startswith("Falha"):
                copied_failed.append({
                    'relative_path': relative_path,
                    'source_path': source_file_path,
                    'destination_path': destination_file_path,
                    'status': copy_status,
                    'error_message': error_message,
                    'timestamp': datetime.now().isoformat()
                })

            with state_lock:
                operation_state['files_processed'] += 1
            update_and_emit_status()

        # --- Geração do Relatório de Cópia ---
        copy_report_session_id = str(uuid.uuid4())
        copy_report_json_filename = f"copy_report_{copy_report_session_id}.json"
        copy_report_filepath = os.path.join(RESULTS_DIR, copy_report_json_filename)

        report_data = {
            "timestamp": datetime.now().isoformat(),
            "comparison_json_used": comparison_json_filename,
            "source_base_directory": source_base_dir,
            "destination_base_directory": destination_base_dir,
            "total_files_attempted": len(files_to_copy),
            "files_copied_successfully": len(copied_success),
            "files_failed_to_copy": len(copied_failed),
            "successful_copies": copied_success,
            "failed_copies": copied_failed
        }

        try:
            with open(copy_report_filepath, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=4, ensure_ascii=False)
            log_and_emit_message('info', f"Relatório de cópia salvo como: {copy_report_json_filename}", force_emit=True)
        except IOError as e:
            log_and_emit_message('error', f"Erro ao salvar relatório de cópia {copy_report_json_filename}: {e}", force_emit=True)

        # Opcional: Gerar um CSV para os arquivos que falharam
        copy_failed_csv_filename = f"copy_failed_{copy_report_session_id}.csv"
        copy_failed_csv_filepath = os.path.join(RESULTS_DIR, copy_failed_csv_filename)
        if copied_failed:
            try:
                with open(copy_failed_csv_filepath, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(["Caminho Relativo", "Caminho Origem", "Caminho Destino", "Status", "Mensagem de Erro", "Timestamp"])
                    for entry in copied_failed:
                        writer.writerow([
                            entry.get('relative_path', 'N/A'),
                            entry.get('source_path', 'N/A'),
                            entry.get('destination_path', 'N/A'),
                            entry.get('status', 'N/A'),
                            entry.get('error_message', 'N/A'),
                            entry.get('timestamp', 'N/A')
                        ])
                log_and_emit_message('info', f"CSV de cópias falhas salvo como: {copy_failed_csv_filename}", force_emit=True)
            except IOError as e:
                log_and_emit_message('error', f"Erro ao salvar CSV de cópias falhas {copy_failed_csv_filename}: {e}", force_emit=True)
        else:
            log_and_emit_message('info', "Nenhum arquivo falhou na cópia. Nenhum CSV de falhas gerado.", force_emit=True)

        log_and_emit_message('info', f"Cópia de arquivos concluída. {len(copied_success)} arquivos copiados, {len(copied_failed)} falhas.", force_emit=True)
        
        socketio.emit('copy_complete', { 
            'copied_count': len(copied_success),
            'failed_count': len(copied_failed),
            'total_attempted': len(files_to_copy),
            'report_json_filename': copy_report_json_filename,
            'report_csv_filename': copy_failed_csv_filename if copied_failed else None
        })

    except Exception as e:
        log_and_emit_message('error', f"Erro crítico durante a operação de cópia: {e}", force_emit=True)
    finally:
        with state_lock:
            operation_state = initial_operation_state.copy() 
            operation_state['all_collected_jsons'] = get_available_info_jsons() 
            operation_state['all_comparison_jsons'] = get_available_comparison_jsons()
            operation_state['all_copy_reports'] = get_available_copy_reports()
        update_and_emit_status("Operação de cópia finalizada.", force_emit=True)
        socketio.emit('operation_ended') 

# --- Rotas Flask ---

@app.route('/', methods=['GET'])
def index():
    with state_lock:
        operation_state['all_collected_jsons'] = get_available_info_jsons()
        operation_state['all_comparison_jsons'] = get_available_comparison_jsons() 
        operation_state['all_copy_reports'] = get_available_copy_reports()
        current_operation_state = operation_state.copy() 
    
    return render_template('index.html', 
                           collected_jsons=current_operation_state['all_collected_jsons'],
                           comparison_jsons=current_operation_state['all_comparison_jsons'],
                           copy_reports=current_operation_state['all_copy_reports'],
                           operation_state=current_operation_state) 

@app.route('/collect', methods=['POST'])
def collect():
    data = request.json
    directory_path = data.get('directory_path')
    collection_type = data.get('collection_type')

    if not directory_path or not collection_type:
        return jsonify({'status': 'error', 'message': 'Caminho do diretório ou tipo de coleta não fornecidos.'}), 400

    if operation_state['running']:
        return jsonify({'status': 'error', 'message': 'Outra operação já está em andamento.'}), 409

    # Inicia a tarefa de coleta em uma nova thread
    threading.Thread(target=perform_collection_task, args=(directory_path, collection_type)).start()
    return jsonify({'status': 'success', 'message': 'Coleta iniciada.'})

@app.route('/compare', methods=['POST'])
def compare():
    data = request.json
    json_origem_filename = data.get('json_origem')
    json_destino_filename = data.get('json_destino')

    if not json_origem_filename or not json_destino_filename:
        return jsonify({'status': 'error', 'message': 'Nomes dos arquivos JSON não fornecidos.'}), 400

    if operation_state['running']:
        return jsonify({'status': 'error', 'message': 'Outra operação já está em andamento.'}), 409

    # Inicia a tarefa de comparação em uma nova thread
    threading.Thread(target=perform_comparison_task, args=(json_origem_filename, json_destino_filename)).start()
    return jsonify({'status': 'success', 'message': 'Comparação iniciada.'})

@app.route('/copy_missing', methods=['POST'])
def copy_missing_files():
    data = request.json
    comparison_json_filename = data.get('comparison_json')

    if not comparison_json_filename:
        return jsonify({'status': 'error', 'message': 'Nome do arquivo JSON de comparação não fornecido.'}), 400
    
    if operation_state['running']:
        return jsonify({'status': 'error', 'message': 'Outra operação já está em andamento.'}), 409
    
    threading.Thread(target=perform_copy_task, args=(comparison_json_filename,)).start()
    return jsonify({'status': 'success', 'message': 'Operação de cópia iniciada.'})


@app.route('/results/<filename>')
def download_file(filename):
    """Permite o download dos arquivos de resultado."""
    return send_from_directory(RESULTS_DIR, secure_filename(filename), as_attachment=True)

@app.route('/info_data/<filename>')
def download_info_file(filename):
    """Permite o download dos arquivos de coleta (info_data)."""
    return send_from_directory(INFO_DIR, secure_filename(filename), as_attachment=True)

@app.route('/report/<json_filename>')
def comparison_report(json_filename):
    """Renderiza a página de relatório de comparação."""
    json_filepath = os.path.join(RESULTS_DIR, secure_filename(json_filename))
    if not os.path.exists(json_filepath):
        return "Relatório de comparação não encontrado.", 404

    try:
        with open(json_filepath, 'r', encoding='utf-8') as f:
            report_data = json.load(f)
        
        timestamp_raw = report_data.get("timestamp", "N/A")
        try:
            timestamp_formatted = datetime.fromisoformat(timestamp_raw).strftime("%d/%m/%Y %H:%M:%S")
        except ValueError:
            timestamp_formatted = timestamp_raw

        csv_filename_for_report = f"not_copied_comparison_{json_filename.replace('comparison_result_', '').replace('.json', '.csv')}"
        csv_available = os.path.exists(os.path.join(RESULTS_DIR, csv_filename_for_report))

        return render_template('comparison_report.html', 
                               report_data=report_data,
                               timestamp=timestamp_formatted,
                               csv_filename=csv_filename_for_report if csv_available else None) # Passa o nome do CSV
    except json.JSONDecodeError:
        return "Erro ao carregar o arquivo JSON do relatório. Formato inválido.", 500
    except Exception as e:
        logger.error(f"Erro ao gerar relatório de comparação de {json_filename}: {e}")
        return "Ocorreu um erro ao gerar o relatório.", 500

@app.route('/copy_report/<json_filename>')
def copy_report(json_filename):
    json_filepath = os.path.join(RESULTS_DIR, secure_filename(json_filename))
    if not os.path.exists(json_filepath):
        return "Relatório de cópia não encontrado ou arquivo JSON excluído.", 404

    try:
        with open(json_filepath, 'r', encoding='utf-8') as f:
            report_data = json.load(f)
        
        timestamp_raw = report_data.get("timestamp", "N/A")
        try:
            timestamp_formatted = datetime.fromisoformat(timestamp_raw).strftime("%d/%m/%Y %H:%M:%S")
        except ValueError:
            timestamp_formatted = timestamp_raw

        csv_filename_for_report = f"copy_failed_{json_filename.replace('copy_report_', '').replace('.json', '.csv')}"
        csv_available = os.path.exists(os.path.join(RESULTS_DIR, csv_filename_for_report))

        return render_template('copy_report.html', 
                               report_data=report_data,
                               timestamp=timestamp_formatted,
                               csv_filename=csv_filename_for_report if csv_available else None,
                               report_json_filename=json_filename) 
    except json.JSONDecodeError:
        return "Erro ao carregar o arquivo JSON do relatório de cópia. Formato inválido.", 500
    except Exception as e:
        logger.error(f"Erro ao gerar relatório de cópia de {json_filename}: {e}")
        return "Ocorreu um erro ao gerar o relatório de cópia.", 500


# --- SocketIO Event Handlers ---

@socketio.on('connect')
def handle_connect():
    log_and_emit_message('info', 'Cliente conectado ao SocketIO.', force_emit=True)
    with state_lock:
        # Garante que as listas sejam atualizadas no estado antes de emitir
        operation_state['all_collected_jsons'] = get_available_info_jsons() 
        operation_state['all_comparison_jsons'] = get_available_comparison_jsons() 
        operation_state['all_copy_reports'] = get_available_copy_reports()
    update_and_emit_status(force_emit=True) # Isso enviará o estado COMPLETO para o frontend

@socketio.on('pause_operation')
def handle_pause():
    with state_lock:
        if operation_state['running'] and not operation_state['paused']:
            pause_event.set()
            operation_state['paused'] = True
            log_and_emit_message('info', 'Operação pausada.', force_emit=True)
            update_and_emit_status("Operação pausada.")

@socketio.on('resume_operation')
def handle_resume():
    with state_lock:
        if operation_state['running'] and operation_state['paused']:
            pause_event.clear()
            operation_state['paused'] = False
            log_and_emit_message('info', 'Operação retomada.', force_emit=True)
            update_and_emit_status("Operação retomada.")

@socketio.on('stop_operation')
def handle_stop():
    with state_lock:
        if operation_state['running']:
            stop_event.set()
            pause_event.clear() # Limpa a pausa se estiver pausado
            operation_state['running'] = False
            operation_state['paused'] = False
            log_and_emit_message('warning', 'Operação interrompida. Finalizando...', force_emit=True)
            update_and_emit_status("Operação sendo interrompida...")

if __name__ == '__main__':
    socketio.run(app, debug=True, allow_unsafe_werkzeug=True) # allow_unsafe_werkzeug=True para execução em desenvolvimento