"""roo-engine — the Roo Voice inference sidecar (IP-178).

phonemize(en-gb) -> llama-server(GGUF, greedy) -> NeuCodec int8 ONNX decode -> WAV.
Frozen to a single binary per platform; supervised by the Tauri shell.
"""
__version__ = "2.0.0"
