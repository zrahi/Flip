"""Lists what candidate on-PC drawing models contain (run by the probe workflow, which can reach Hugging Face)."""
import json
import urllib.request

REPOS = ["onnxruntime/sd-turbo", "IDKiro/sdxs-512-0.9", "IDKiro/sdxs-512-dreamshaper", "rupeshs/sdxs-512-0.9-openvino",
         "rupeshs/sd-turbo-openvino", "schmuell/sd-turbo-ort-web", "stabilityai/sd-turbo", "OpenVINO/sd-turbo-int8-ov",
         "rupeshs/sdxs-512-0.9-orig-vae-openvino", "Intel/sd-1.5-lcm-openvino", "nmkd/stable-diffusion-1.5-onnx-fp16",
         "aislamov/stable-diffusion-2-1-base-onnx", "jdp8/sd-turbo-onnx", "tlwu/sd-turbo-onnxruntime"]

for repo in REPOS:
    try:
        req = urllib.request.Request(f"https://huggingface.co/api/models/{repo}/tree/main?recursive=true",
                                     headers={"User-Agent": "Flip/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            items = json.load(r)
        files = [(i["path"], i.get("size") or (i.get("lfs") or {}).get("size") or 0) for i in items if i.get("type") == "file"]
        total = sum(s for _, s in files)
        print(f"== {repo}: {len(files)} files, {total / 1e9:.2f} GB")
        for path, size in files:
            if size > 100_000 or path.endswith((".json", ".txt")):
                print(f"   {size / 1e6:9.1f} MB  {path}")
    except Exception as e:
        print(f"== {repo}: {e}")
