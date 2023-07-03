# sd-model-manager

A desktop application and companion web server for browsing and managing Stable Diffusion models (embeddings, LoRAs, etc.) and their metadata.

Can be used standalone with the included frontend, embedded into ComfyUI for use with their ecosystem (*TODO*), or repurposed as an independent API server.

## Usage

First install the requirements:

```
pip install -r requirements.txt
```

Next edit `config.yml` to contain your model paths:

``` yaml
listen: 0.0.0.0
port: 7779
model-paths: ["C:/path/to/loras"]
```

Then the built-in GUI can be run as follows:

```
python client.py
```

To run the API server standalone with hot reloading:

```
adev runserver -p 7779 main.py
```
