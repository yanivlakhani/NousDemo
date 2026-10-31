"""Run the versioned ElevenLabs configuration with the Modal-held API key.

Usage: modal run scripts/configure_elevenlabs.py
"""

import os

import modal


app = modal.App("nous-elevenlabs-configure")
secret = modal.Secret.from_name("pathway-elevenlabs")
image = modal.Image.debian_slim().pip_install("httpx").add_local_python_source("scripts")


@app.function(secrets=[secret], image=image)
def apply_configuration():
    import httpx
    from scripts.elevenlabs_agent_config import configure, verify

    agent_id = os.environ["ELEVENLABS_AGENT_ID"]
    with httpx.Client(headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]}, timeout=30) as client:
        change = configure(client, agent_id=agent_id)
        return {"change": change, "verified": verify(client, agent_id=agent_id)}


@app.local_entrypoint()
def main():
    print(apply_configuration.remote())
