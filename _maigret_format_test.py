import subprocess, sys, json, tempfile, pathlib, os

outdir = pathlib.Path(tempfile.mkdtemp())
env = os.environ.copy()
env["PYTHONIOENCODING"] = "utf-8"
env["PYTHONUTF8"] = "1"

result = subprocess.run(
    [sys.executable, "-m", "maigret", "github", "--no-progressbar", "--no-color",
     "--timeout", "5", "-J", "simple", "--no-recursion", "--top-sites", "30",
     "--folderoutput", str(outdir)],
    capture_output=True, text=True, timeout=90, env=env,
)
files = list(outdir.glob("*.json"))
print("JSON files:", files)
if files:
    data = json.loads(files[0].read_text(encoding="utf-8"))
    for username, sites in data.items():
        print(f"username key: {username!r}")
        for site, info in list(sites.items())[:5]:
            status = info.get("status", {})
            url = info.get("url_user", "")
            print(f"  site={site!r}  status_id={status.get('id')}  url={url}")
        break
else:
    print("No JSON file found")
    print("stdout:", result.stdout[:300])
    print("stderr:", result.stderr[:300])
