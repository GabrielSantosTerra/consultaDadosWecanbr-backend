import requests
import base64
import os
import time  # Para calcular o tempo de execução

# Função para realizar login e obter o authorization_key
def login(conta, usuario, senha):
    base_url = "http://ged.byebyepaper.com.br:9090/idocs_bbpaper/api/v1"
    endpoint = "/login"
    url = base_url + endpoint

    payload = {
        'conta': conta,
        'usuario': usuario,
        'senha': senha,
        'id_interface': 'CLIENT_WEB'  # Identificação da interface de acesso
    }

    headers = {
        'Content-Type': 'application/x-www-form-urlencoded; charset=ISO-8859-1;'
    }

    try:
        # Realiza o POST com os dados de login
        response = requests.post(url, headers=headers, data=payload)

        # Verifica se a resposta foi bem-sucedida (status code 200)
        response.raise_for_status()

        # Tenta converter a resposta para JSON
        try:
            response_json = response.json()

            # Verifica se o campo 'authorization_key' está presente na resposta
            authorization_key = response_json.get('authorization_key')
            if authorization_key:
                return authorization_key  # Retorna o authorization_key
            else:
                print("Authorization Key não encontrada na resposta.")
                return None
        except ValueError:
            print("Resposta não é um JSON válido.")
            return None

    except requests.exceptions.RequestException as e:
        # Em caso de erro na requisição, exibe a mensagem
        print(f"Erro ao fazer a requisição: {e}")
        return None

# Função para buscar templates
def searchTemplate(authorization_key, id_tipo):
    base_url = "http://ged.byebyepaper.com.br:9090/idocs_bbpaper/api/v1"
    endpoint = "/templates/getall"
    url = base_url + endpoint

    headers = {
        'Authorization': authorization_key,  # Bearer token
        'Content-Type': 'application/x-www-form-urlencoded; charset=ISO-8859-1;'
    }

    try:
        # Realiza o GET para buscar os templates
        response = requests.get(url, headers=headers)

        # Verifica se a resposta foi bem-sucedida (status code 200)
        response.raise_for_status()

        # Tenta converter a resposta para JSON
        try:
            response_json = response.json()

            # Verifica se há erro na resposta
            if response_json.get('error', True):
                print(f"Erro na resposta: {response_json.get('message', 'Mensagem não encontrada')}")
                return None

            # Obtém a lista de templates
            templates = response_json.get('templates', [])

            # Percorre os templates e procura pelo id_tipo desejado
            for template in templates:

                    # Retorna a combinação 'id_tipo - nome_tipo'
                    nome_pasta = f"{template['id_tipo']} - {template['nome_tipo']}"
                    return nome_pasta

            # Caso não encontre o template com o id_tipo fornecido
            print(f"Template com id_tipo {id_tipo} não encontrado.")
            return None

        except ValueError:
            print("Resposta não é um JSON válido.")
            return None

    except requests.exceptions.RequestException as e:
        # Em caso de erro na requisição de templates, exibe a mensagem
        print(f"Erro ao fazer a requisição: {e}")
        return None

# Função para realizar a busca de documentos
def searchDocuments(authorization_key, id_tipo, cpFiltros):
    base_url = "http://ged.byebyepaper.com.br:9090/idocs_bbpaper/api/v1"
    endpoint = "/documents/search"
    url = base_url + endpoint

    # Inicializa a string do payload
    payload = f"id_tipo={id_tipo}"

    # Adiciona os filtros cp[] à string do payload, se existirem
    if cpFiltros:
        for filtro in cpFiltros:
            for key, value in filtro.items():
                if key == "cp[]":
                    payload += f"&cp[]={value}"  # Adiciona o filtro cp[] ao payload

    # Continua a construção do payload com os outros parâmetros
    payload += f"&ordem=&dt_criacao=&pagina=1&colecao="

    headers = {
        'Authorization': authorization_key,  # Bearer token
        'Content-Type': 'application/x-www-form-urlencoded; charset=ISO-8859-1;'
    }

    all_documents = []  # Lista para armazenar todos os documentos encontrados

    for page in range(1, 1000):  # Iteração nas páginas de 1 até 999
        payload = payload.replace("pagina=1", f"pagina={page}")  # Atualiza a página na string do payload

        try:
            # Realiza o POST com os dados de busca
            response = requests.post(url, headers=headers, data=payload)

            # Verifica se a resposta foi bem-sucedida
            response.raise_for_status()

            # Tenta converter a resposta para JSON
            try:
                response_json = response.json()

                # Verifica se houve erro na resposta
                if response_json.get('error', True):
                    print(f"Erro na resposta: {response_json.get('message', 'Mensagem não encontrada')}")
                    break  # Se houver erro, interrompe o loop

                # Obtém os documentos da resposta
                documents = response_json.get("documents", [])
                totalpaginas = response_json["variables"].get("totalpaginas", 0)

                if documents:
                    # Adiciona os documentos encontrados à lista
                    all_documents.extend(documents)
                    print(f"Página {page} de {totalpaginas} carregada com sucesso.")
                else:
                    print(f"Nenhum documento encontrado na página {page}.")
                    break  # Se não houver documentos, interrompe a busca

                # Se a página atual for maior que o total de páginas, sai do loop
                if page >= totalpaginas:
                    print(f"Todas as {totalpaginas} páginas foram processadas.")
                    break

            except ValueError:
                print("Resposta não é um JSON válido.")
                break  # Interrompe o loop caso a resposta não seja JSON

        except requests.exceptions.RequestException as e:
            # Em caso de erro na requisição de busca, exibe a mensagem
            print(f"Erro ao fazer a requisição: {e}")
            break  # Interrompe o loop em caso de erro de requisição

    return all_documents  # Retorna a lista completa de documentos encontrados

# Função para realizar o download de um documento
def downloadDocument(authorization_key, id_tipo, id_documento, nomearquivo, pasta_destino):
    base_url = "http://ged.byebyepaper.com.br:9090/idocs_bbpaper/api/v1"
    endpoint = "/documents/download"
    url = base_url + endpoint

    payload = {
        'id_tipo': id_tipo,  # ID do tipo de documento
        'id_documento': id_documento  # ID do documento a ser baixado
    }

    headers = {
        'Authorization': authorization_key,  # Bearer token
        'Content-Type': 'application/x-www-form-urlencoded; charset=ISO-8859-1;'
    }

    try:
        # Realiza o POST para o download do documento
        response = requests.post(url, headers=headers, data=payload)

        # Verifica se a resposta foi bem-sucedida
        response.raise_for_status()

        # Tenta extrair o conteúdo da resposta
        try:
            base64string = response.text  # Resposta contém o arquivo em base64
            # Decodificando o conteúdo base64
            file_data = base64.b64decode(base64string)

            # Caminho completo do arquivo na pasta destino
            file_path = os.path.join(pasta_destino, nomearquivo)

            # Salva o arquivo na pasta de destino
            with open(file_path, 'wb') as file:
                file.write(file_data)

            print(id_documento + f" - Arquivo baixado com sucesso. {file_path}")  # Mensagem de sucesso
            return True  # Indica que o download foi bem-sucedido
        except ValueError:
            print("Resposta não é um JSON válido.")
            return False  # Indica falha no download

    except requests.exceptions.RequestException as e:
        # Em caso de erro na requisição de download, exibe a mensagem
        print(f"Erro ao fazer a requisição de download: {e}")
        return False  # Retorna False em caso de erro

# Dados de login
conta = ""
usuario = ""
senha = ""  # Senha do usuário
id_tipos = [ 0, 1, 2 ]  # Lista com vários id_tipo para serem processados
filtrosCp = [ { "cp[]": "" } ] # Verificar que cada template possui campos diferentes de filtros!!

# Chama a função de login e obtém o authorization_key
authorization_key = login(conta, usuario, senha)

# Só chama a função searchDocuments se o login for bem-sucedido
if authorization_key:
    # Processa cada id_tipo na lista
    for id_tipo in id_tipos:
        # Chama a função searchTemplate para obter o nome da pasta
        nome_pasta = searchTemplate(authorization_key, id_tipo)

        if nome_pasta:
            # Cria a pasta se não existir
            if not os.path.exists(nome_pasta):
                os.makedirs(nome_pasta)

            # Inicia o cronômetro de tempo
            start_time = time.time()

            # Realiza a busca de documentos com o authorization_key obtido
            documentos = searchDocuments(authorization_key, id_tipo, filtrosCp)

            # Se documentos foram encontrados, realiza o download de cada um
            if documentos:
                total_documentos = len(documentos)  # Total de documentos encontrados
                total_baixados = 0  # Contador de documentos baixados

                for i, doc in enumerate(documentos, 1):  # Inicia o contador 'i' a partir de 1
                    # Imprime o progresso (índice atual de documentos / total de documentos)
                    print(f"Processando {i} de {total_documentos} documentos...")

                    # Para cada documento, chama a função de downloadDocument
                    if downloadDocument(authorization_key, id_tipo, doc["id_documento"], doc["nomearquivo"], nome_pasta):
                        total_baixados += 1  # Incrementa o contador se o download for bem-sucedido

                # Finaliza o tempo de execução
                end_time = time.time()
                elapsed_time = end_time - start_time  # Tempo de execução em segundos

                # Salva o log na pasta de download
                log_file_path = os.path.join(nome_pasta, "log.txt")

                with open(log_file_path, "w") as log_file:
                    log_file.write(f"Total de documentos encontrados: {total_documentos}\n")
                    log_file.write(f"Total de documentos baixados: {total_baixados}\n")
                    log_file.write(f"Tempo total de processamento: {elapsed_time:.2f} segundos\n")

                print(f"Log salvo em: {log_file_path}")
            else:
                print("Nenhum documento encontrado para download.")
        else:
            print(f"Erro: Template com id_tipo {id_tipo} não encontrado.")
else:
    print("Erro: Não foi possível obter o authorization_key.")



