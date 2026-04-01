#!/bin/bash
set -e

echo "Setting up Python environment..."
python -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "Downloading spaCy English model..."
.venv/bin/python -m spacy download en_core_web_sm

echo "Installing Jupyter kernel..."
.venv/bin/python -m ipykernel install --user --name=python3 --display-name=".venv"

echo "Configuring environment..."
cp env.template .env

# If OPENAI_API_KEY is set as a Codespace secret, inject it into .env
if [ -n "$OPENAI_API_KEY" ]; then
    sed -i "s/^OPENAI_API_KEY=$/OPENAI_API_KEY=$OPENAI_API_KEY/" .env
    echo "OpenAI API key detected and configured."
fi

echo "Setup complete!"
