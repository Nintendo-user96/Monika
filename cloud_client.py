import requests

CLOUD_BASE_URL = "http://YOUR.SERVER.IP:5000"

def upload_file(local_path, remote_filename):
    with open(local_path, "rb") as f:
        data = f.read()

    url = f"{CLOUD_BASE_URL}/upload/{remote_filename}"
    r = requests.post(url, data=data)
    print(f"Upload {remote_filename}: {r.status_code} {r.text}")

def download_file(remote_filename, local_path):
    url = f"{CLOUD_BASE_URL}/download/{remote_filename}"
    r = requests.get(url)
    if r.status_code == 200:
        with open(local_path, "wb") as f:
            f.write(r.content)
        print(f"Downloaded {remote_filename} to {local_path}")
    else:
        print(f"Error: {r.status_code} {r.text}")

def list_files():
    url = f"{CLOUD_BASE_URL}/list"
    r = requests.get(url)
    if r.status_code == 200:
        print("Files:", r.json())
    else:
        print(f"Error: {r.status_code} {r.text}")
