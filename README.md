Comparador e Copiador de Arquivos
Este projeto Flask oferece uma interface web intuitiva para comparar e copiar arquivos entre diretórios locais. Ideal para sincronização de pastas, backup seletivo ou simplesmente para identificar diferenças entre duas estruturas de diretórios.

Recursos Principais
Coleta de Dados de Pastas: Gera relatórios detalhados (.json) de arquivos e diretórios de um caminho especificado, útil para auditoria e preparação para comparação.

Comparação de Pastas: Analisa dois relatórios de coleta (.json) (um de origem e um de destino) para identificar:

Arquivos presentes na origem mas ausentes no destino.

Arquivos presentes em ambos, mas com diferenças de tamanho ou hash (indicando modificação).

Arquivos no destino que não existem na origem (opcionalmente).

Gera relatórios de comparação (.json) e um CSV dos arquivos a serem copiados/atualizados.

Cópia Seletiva de Arquivos: Utiliza um relatório de comparação para copiar apenas os arquivos ausentes ou diferentes da pasta de origem para a pasta de destino, otimizando o processo e evitando cópias desnecessárias.

Interface Web Amigável: Desenvolvido com Flask e Bootstrap, oferece um fluxo de trabalho passo a passo, com barra de progresso, logs em tempo real e alertas dinâmicos.

Seleção de Pasta Gráfica: Permite selecionar diretórios através de uma janela de diálogo nativa do sistema operacional, eliminando a necessidade de digitar caminhos complexos.

Gerenciamento de Relatórios: Baixe e visualize relatórios de coleta, comparação e cópia diretamente pela interface.

Controle de Operação: Pause, retome ou pare operações em andamento.

Tecnologias Utilizadas
Backend: Python 3, Flask

Frontend: HTML5, CSS3, JavaScript, Bootstrap 5, Font Awesome

Comunicação: WebSockets (Flask-SocketIO) para feedback em tempo real

Seleção de Pasta: tkinter (módulo padrão do Python)

Gerenciamento de Pastas/Arquivos: os, shutil, hashlib (módulos padrão do Python)

Configuração e Instalação
Siga os passos abaixo para configurar e rodar o projeto em sua máquina local.

Pré-requisitos
Python 3.8+

pip (gerenciador de pacotes do Python)

1. Clonar o Repositório
Bash

git clone <URL_DO_SEU_REPOSITORIO>
cd comparador-copiador-arquivos
2. Criar e Ativar o Ambiente Virtual (Recomendado)
É uma boa prática usar um ambiente virtual para isolar as dependências do projeto.

Bash

python -m venv venv
# No Windows:
.\venv\Scripts\activate
# No macOS/Linux:
source venv/bin/activate
3. Instalar Dependências
Com o ambiente virtual ativado, instale as bibliotecas necessárias:

Bash

pip install -r requirements.txt
4. Estrutura de Pastas de Dados
Crie as pastas necessárias para os relatórios na raiz do projeto:

Bash

mkdir collected_data
mkdir comparison_results
mkdir copy_reports
5. Configurar o Favicon (Opcional)
Se você tiver um favicon.ico, coloque-o dentro da pasta static/.

6. Executar a Aplicação
Bash

python app.py
Após executar, o terminal mostrará uma mensagem indicando o endereço local onde a aplicação está rodando (ex: http://127.0.0.1:5000/). Abra este endereço em seu navegador.

Definição das Ações (Etapas na Interface)
A interface é dividida em etapas sequenciais para facilitar o fluxo de trabalho.

Etapa 1: Coletar Informações de Pastas
Esta etapa é usada para criar um "instantâneo" do conteúdo de uma pasta específica.

Caminho Completo da Pasta:

Ação: Insira ou utilize o botão "Procurar Pasta..." para selecionar o caminho absoluto da pasta (ex: C:\MeusProjetos, /home/usuario/documentos).

Definição: Este é o diretório que você deseja que a aplicação escaneie e catalogue todos os seus arquivos e subdiretórios, incluindo metadados como tamanho e hash MD5 para futuras comparações.

Propósito da Coleta:

Ação: Selecione se a pasta é uma "Pasta de Origem" (a fonte dos arquivos a serem comparados/copiados) ou uma "Pasta de Destino" (onde os arquivos serão verificados/recebidos).

Definição: Essa categorização ajuda a organizar seus relatórios e a usar o JSON correto nas etapas subsequentes.

Iniciar Coleta de Dados:

Ação: Clique neste botão para começar o processo de varredura da pasta.

Definição: A aplicação percorrerá a estrutura de diretórios, coletando informações de cada arquivo e salvando-as em um arquivo JSON na pasta collected_data/. O status e o progresso serão exibidos na seção de monitoramento.

Etapa 2: Comparar Pastas
Nesta etapa, você usará dois relatórios de coleta (JSONs) para identificar diferenças entre duas pastas.

JSON de Coleta da Origem:

Ação: Selecione um arquivo JSON gerado na Etapa 1 que representa a pasta de origem.

Definição: Este relatório contém a lista de arquivos que você espera encontrar (ou copiar) no destino.

JSON de Coleta do Destino:

Ação: Selecione um arquivo JSON gerado na Etapa 1 que representa a pasta de destino.

Definição: Este relatório contém a lista de arquivos que a aplicação verificará para encontrar correspondências com a origem.

Iniciar Comparação de Pastas:

Ação: Clique neste botão para começar o processo de comparação.

Definição: A aplicação irá cruzar os dados dos dois JSONs, identificando arquivos ausentes no destino, arquivos com tamanhos ou hashes diferentes. Um novo relatório de comparação será gerado em comparison_results/, além de um CSV listando os arquivos que precisam ser copiados/atualizados.

Etapa 3: Copiar Arquivos Ausentes/Diferentes
Esta etapa usa um relatório de comparação para copiar seletivamente arquivos da origem para o destino.

Relatório de Comparação para Cópia:

Ação: Selecione um arquivo JSON de comparação gerado na Etapa 2.

Definição: Este relatório serve como um mapa, indicando quais arquivos da pasta de origem estão ausentes ou diferentes na pasta de destino e, portanto, precisam ser copiados.

Iniciar Cópia de Arquivos:

Ação: Clique neste botão para começar a cópia dos arquivos.

Definição: A aplicação copiará apenas os arquivos identificados no relatório de comparação. Um novo relatório de cópia será gerado em copy_reports/, detalhando o sucesso ou falha de cada cópia.

Etapa 4: Visualizar e Gerenciar Relatórios
Nesta seção, você pode acessar e baixar todos os relatórios gerados pelo sistema.

Relatórios de Coleta Disponíveis: Lista todos os JSONs gerados na Etapa 1.

Ações: Baixar o arquivo JSON.

Relatórios de Comparação Disponíveis: Lista todos os JSONs e CSVs gerados na Etapa 2.

Ações: Visualizar o relatório completo em uma nova aba (JSON formatado), baixar o arquivo JSON bruto ou baixar o CSV de arquivos a serem copiados/atualizados.

Relatórios de Cópia Disponíveis: Lista todos os JSONs e CSVs de falhas de cópia gerados na Etapa 3.

Ações: Visualizar o relatório de cópia em uma nova aba (JSON formatado), baixar o JSON bruto ou baixar o CSV de arquivos que falharam na cópia.

Monitoramento da Operação
Na parte superior da página, você encontrará a seção de monitoramento de operação:

Status Atual: Exibe o estado da operação em tempo real (ex: "Ocioso", "Coletando dados...", "Copiando arquivos...").

Arquivos Processados: Mostra a contagem de arquivos já tratados em relação ao total estimado.

Diretório em Andamento: Informa qual diretório está sendo processado no momento.

Barra de Progresso: Visualiza o andamento geral da operação.

Botões de Controle:

Pausar: Suspende a operação em andamento.

Retomar: Continua uma operação pausada.

Parar: Interrompe completamente a operação atual.

Logs da Aplicação
Uma seção de "Logs da Aplicação" na parte inferior da página exibe mensagens em tempo real sobre o que a aplicação está fazendo, incluindo informações, avisos e erros. Isso é útil para depuração e para acompanhar o progresso detalhado.

Desenvolvimento
Para desenvolvedores que desejam contribuir ou estender o projeto:

Estrutura de Código
app.py: Contém as rotas Flask (@app.route), a lógica de SocketIO (@socketio.on) para comunicação em tempo real, e as funções principais para varredura, comparação e cópia de arquivos.

main.js: Lida com a interação do usuário na interface, envio de formulários via AJAX, e o recebimento e exibição de mensagens de status e logs via WebSockets.

index.html: Define a estrutura da página, os formulários e os elementos visuais, e utiliza Jinja2 para renderizar dados dinâmicos do backend.

comparison_report.html: Template para exibir relatórios de comparação detalhados em uma tabela interativa.

Endpoints da API (simplificado)
POST /collect_data: Inicia a coleta de dados de uma pasta.

POST /compare_directories: Inicia a comparação entre dois relatórios de coleta.

POST /copy_files: Inicia a cópia de arquivos com base em um relatório de comparação.

POST /browse_directory: Abre a janela de seleção de pasta nativa.

GET /download/<filename>: Baixa um arquivo de relatório.

GET /info_file/<filename>: Baixa um JSON de coleta (usado para diferenciá-lo de outros downloads).

GET /comparison_report/<json_filename>: Exibe o relatório de comparação em uma nova página.

GET /copy_report/<json_filename>: Exibe o relatório de cópia em uma nova página.

GET /status: Endpoint para obter o estado atual da operação.

Mensagens SocketIO
A aplicação usa SocketIO para comunicação em tempo real entre o backend e o frontend:

status_update: Envia atualizações de progresso, status e diretório atual.

log_message: Envia mensagens de log com diferentes níveis (info, success, warning, error, debug).

alert_message: Envia mensagens de alerta para serem exibidas em toasts na interface.
