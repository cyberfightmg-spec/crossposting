from tools.pinterest import get_pinterest_client

if __name__ == "__main__":
    client = get_pinterest_client()
    print("✅ Pinterest авторизован, куки сохранены в /root/crossposting/pinterest_creds")