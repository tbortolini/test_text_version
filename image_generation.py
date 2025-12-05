import os
import base64
import subprocess
from datetime import date
from pathlib import Path
import re

import streamlit as st
from openai import OpenAI

# -------------------------------------------------------------------
# CONFIGURAÇÕES GERAIS
# -------------------------------------------------------------------
# Pasta "data" do projeto SP01 (ajuste se necessário)


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = REPO_ROOT / "Data"   # ajuste para o seu layout real

BASE_DATA_DIR = Path(os.environ.get("SP01_DATA_DIR", DEFAULT_DATA_DIR))

# ID do participante cujo trials serão usados
# Ex.: "TB"
PARTICIPANT_ID = os.environ.get("PARTICIPANT_ID", "TB2")

# Branch git para dar push
GIT_BRANCH = os.environ.get("GIT_BRANCH", "main")

# Nome do remoto
GIT_REMOTE = os.environ.get("GIT_REMOTE", "origin")

# Cliente OpenAI (usa OPENAI_API_KEY do ambiente)
client = OpenAI()


# -------------------------------------------------------------------
# AUTENTICAÇÃO SIMPLES
# -------------------------------------------------------------------
def check_password() -> bool:
    """
    Login simples: compara senha digitada com APP_PASSWORD do ambiente.
    Armazena estado em st.session_state.
    """

    def password_entered():
        pwd_env = os.environ.get("APP_PASSWORD")
        if pwd_env is None:
            st.error(
                "APP_PASSWORD não configurada no ambiente. "
                "Defina a variável de ambiente no servidor."
            )
            st.stop()

        if st.session_state["password"] == pwd_env:
            st.session_state["password_correct"] = True
        else:
            st.session_state["password_correct"] = False

    # Se já logou
    if st.session_state.get("password_correct", False):
        return True

    st.subheader("Login")
    st.write("Insira a senha para acessar o app.")

    st.text_input(
        "Senha",
        type="password",
        on_change=password_entered,
        key="password",
    )

    if st.session_state.get("password_correct") is False:
        st.error("Senha incorreta.")

    return False


# -------------------------------------------------------------------
# FUNÇÕES AUXILIARES DE TRIALS
# -------------------------------------------------------------------
def listar_trials_de_participante(base_dir: Path, participant_id: str):
    """
    Retorna lista de trials APENAS de um participante específico.
    Estrutura esperada:
    base_dir / {PARTICIPANT_ID} / trials / {PASTA_TRIAL}
    """
    trials_info = []

    participant_dir = base_dir / participant_id
    trials_dir = participant_dir / "trials"

    if not trials_dir.exists():
        return trials_info

    for trial_dir in sorted(trials_dir.iterdir()):
        if not trial_dir.is_dir():
            continue

        trial_folder_name = trial_dir.name
        label = f"{participant_id} | {trial_folder_name}"

        trials_info.append(
            {
                "label": label,
                "participant_id": participant_id,
                "trial_folder_name": trial_folder_name,
                "path": trial_dir,
            }
        )

    return trials_info


def carregar_resposta_texto(trial_path: Path) -> str | None:
    """
    Procura um arquivo *_response_text.txt na pasta do trial
    e retorna o conteúdo.
    """
    candidates = list(trial_path.glob("*_response_text.txt"))
    if not candidates:
        return None

    candidates.sort()
    response_file = candidates[0]

    try:
        return response_file.read_text(encoding="utf-8")
    except Exception as e:
        st.error(f"Erro ao ler o arquivo de resposta: {e}")
        return None


def encontrar_imagem_existente(trial_path: Path) -> Path | None:
    """
    Verifica se já existe um arquivo com padrão:
    SUBJ_TRIALXX_GPT_IMAGE_YYYY_MM_DD.png
    (qualquer data).
    Retorna o primeiro encontrado (ordenado).
    """
    # Padrão: *_GPT_IMAGE_*.png é suficiente para achar as imagens
    candidates = list(trial_path.glob("*_GPT_IMAGE_*.png"))
    if not candidates:
        return None

    candidates.sort()
    return candidates[0]


def gerar_nome_arquivo_imagem(
    participant_id: str,
    trial_folder_name: str,
    today: date | None = None,
) -> str:
    """
    Gera o nome no formato:
    SUBJ_TRIALXX_GPT_IMAGE_YYYY_MM_DD.png
    onde:
      SUBJ  = participant_id
      TRIAL = número extraído de TrialXX no nome da pasta do trial
    Ex. pasta: TB_Trial01_2025-07-16_Target_0824
        -> SUBJ = TB
        -> TRIALXX = TRIAL01
    """
    if today is None:
        today = date.today()

    match = re.match(r"([^_]+)_Trial(\d+)_", trial_folder_name)
    if match:
        subj = match.group(1)
        trial_num = match.group(2)
    else:
        # fallback se o padrão não bater
        subj = participant_id
        trial_num = "XX"

    date_str = today.strftime("%Y_%m_%d")
    filename = f"{subj}_TRIAL{trial_num}_GPT_IMAGE_{date_str}.png"
    return filename


# -------------------------------------------------------------------
# FUNÇÕES OPENAI + GIT
# -------------------------------------------------------------------
def gerar_imagem_a_partir_do_texto(texto_resposta: str) -> bytes:
    """
    Chama a API de imagens da OpenAI e retorna os bytes da imagem.
    """
    prompt = (
        "Crie uma ilustração sem texto escrito, "
        "inspirada no seguinte parágrafo. "
        "Não escreva palavras na imagem, apenas elementos visuais:\n\n"
        f"{texto_resposta}"
    )

    img = client.images.generate(
        model="gpt-image-1-mini",
        prompt=prompt,
        n=1,
        size="1024x1024",
    )

    b64 = img.data[0].b64_json
    image_bytes = base64.b64decode(b64)
    return image_bytes


def git_add_commit_push(file_path: Path, trial_folder_name: str):
    """
    Faz git add/commit/push do arquivo de imagem.
    Assume:
      - app está em um repo git (com .git)
      - remoto e branch configurados
    """
    repo_root = Path(".").resolve()  # supondo app na raiz do repo

    # 1) git add
    rel_path = file_path.relative_to(repo_root)
    subprocess.run(["git", "add", str(rel_path)], check=False)

    # 2) git commit
    commit_msg = f"Add GPT image for {trial_folder_name}"
    subprocess.run(["git", "commit", "-m", commit_msg], check=False)

    # 3) git push
    subprocess.run(["git", "push", GIT_REMOTE, GIT_BRANCH], check=False)


# -------------------------------------------------------------------
# APLICAÇÃO STREAMLIT
# -------------------------------------------------------------------
st.set_page_config(
    page_title="SP01 – Gerador de Imagens por Trial",
    layout="centered",
)

st.title("SP01 – Gerar imagem OpenAI por trial")

if not check_password():
    st.stop()

st.success(f"Login efetuado. Participante configurado: **{PARTICIPANT_ID}**")

st.write(
    "Este app permite selecionar um **trial** de um participante específico, "
    "gerar uma imagem com a API da OpenAI a partir da **resposta do trial** "
    "e salvar a imagem na pasta do trial com commit automático no repositório."
)

st.markdown(
    f"- Pasta base de dados: `{BASE_DATA_DIR}`  \n"
    f"- Participante fixo: **{PARTICIPANT_ID}**"
)

# 1) Listar trials do participante
trials = listar_trials_de_participante(BASE_DATA_DIR, PARTICIPANT_ID)

if not trials:
    st.warning(
        "Nenhum trial encontrado para esse participante. "
        "Verifique se BASE_DATA_DIR e PARTICIPANT_ID estão corretos."
    )
    st.stop()

labels = [t["label"] for t in trials]
selected_label = st.selectbox("Selecione o trial:", labels)

selected_trial = next(t for t in trials if t["label"] == selected_label)
trial_path = selected_trial["path"]
trial_folder_name = selected_trial["trial_folder_name"]

st.markdown(f"**Pasta do trial:** `{trial_path}`")

# 2) Carregar texto da resposta
resposta_texto = carregar_resposta_texto(trial_path)
if resposta_texto is None:
    st.error("Nenhum arquivo *_response_text.txt foi encontrado neste trial.")
    st.stop()

with st.expander("Ver resposta completa do participante"):
    st.text(resposta_texto)

# 3) Verificar se já existe imagem
existing_img_path = encontrar_imagem_existente(trial_path)

if existing_img_path:
    st.success("Este trial **já possui** uma imagem gerada.")
    st.image(
        str(existing_img_path),
        caption=f"Imagem existente ({existing_img_path.name})",
    )
    st.info("Não é possível gerar outra imagem para este trial.")
else:
    st.info("Ainda **não existe** imagem gerada para este trial.")

    if st.button("Gerar imagem com OpenAI para este trial"):
        with st.spinner("Gerando imagem e salvando no repositório..."):
            # 4) Gerar imagem
            try:
                image_bytes = gerar_imagem_a_partir_do_texto(resposta_texto)
            except Exception as e:
                st.error(f"Erro ao gerar imagem com a API OpenAI: {e}")
                st.stop()

            # 5) Definir nome de arquivo SUBJ_TRIALXX_GPT_IMAGE_YYYY_MM_DD
            filename = gerar_nome_arquivo_imagem(
                selected_trial["participant_id"],
                trial_folder_name,
            )
            img_path = trial_path / filename

            # 6) Salvar arquivo
            try:
                img_path.write_bytes(image_bytes)
            except Exception as e:
                st.error(f"Erro ao salvar a imagem no repositório: {e}")
                st.stop()

            # 7) git add/commit/push
            try:
                git_add_commit_push(img_path, trial_folder_name)
            except Exception as e:
                st.warning(
                    f"Imagem salva, mas houve erro no git add/commit/push: {e}. "
                    "Você pode fazer o commit/push manualmente."
                )
            else:
                st.success("Imagem salva e git add/commit/push executado (verifique logs).")

            # 8) Mostrar imagem
            st.image(
                image_bytes,
                caption=f"Nova imagem gerada ({filename})",
            )
            st.info("A partir de agora, este trial não poderá gerar outra imagem.")
