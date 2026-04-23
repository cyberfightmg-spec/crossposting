#!/usr/bin/env python3
import os
import sys
import logging
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from integrations.vmos.client import VmosClient
from integrations.vmos.check_env import check_vmos_env

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def test_env():
    print("=" * 60)
    print("TEST 1: Environment Check")
    print("=" * 60)
    if not check_vmos_env(stop_on_missing=False):
        print("\n[WARNING] Some variables missing - will attempt API call anyway\n")
    print("[OK] Environment check passed (or continuing for testing)!\n")
    return True


def test_connection():
    print("=" * 60)
    print("TEST 2: VMOS API Connection Test")
    print("=" * 60)

    try:
        client = VmosClient()
        print(f"[INFO] Client initialized with host: {client.host}")
        print(f"[INFO] Access Key: {client.ak[:8]}...{client.ak[-4:]}")
    except ValueError as e:
        print(f"[ERROR] {e}")
        return None
    except Exception as e:
        print(f"[ERROR] Failed to create client: {e}")
        return None

    print("\n[TEST] Getting instance list...")
    try:
        result = client.get_instance_list(page=1, rows=5)
        print(f"[RESPONSE] {result}")

        code = result.get("code")
        msg = result.get("msg", "")
        data = result.get("data", {})

        if code == 200:
            print(f"[OK] Connection successful!")
            page_data = data.get("pageData", [])
            total = data.get("total", 0)
            print(f"[INFO] Total instances: {total}")
            if page_data:
                print(f"[INFO] First instance: {page_data[0].get('padCode')}")
            return {"client": client, "instances": page_data}
        else:
            print(f"[ERROR] API returned code {code}: {msg}")
            return None

    except Exception as e:
        print(f"[ERROR] Connection test failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_sts_token(client, instances):
    print("\n" + "=" * 60)
    print("TEST 3: STS Token Test")
    print("=" * 60)

    if not instances:
        print("[WARN] No instances available for STS token test")
        return None

    pad_code = instances[0].get("padCode")
    if not pad_code:
        print("[ERROR] No padCode found in instance")
        return None

    print(f"[INFO] Requesting STS token for instance: {pad_code}")

    try:
        result = client.get_sts_token(pad_code)
        print(f"[RESPONSE] {result}")

        code = result.get("code")
        msg = result.get("msg", "")
        data = result.get("data", {})

        if code == 200:
            print("[OK] STS token received!")
            access_token = data.get("accessToken")
            if access_token:
                print(f"[INFO] Access Token: {access_token[:20]}...")
            else:
                print("[WARN] No accessToken in response")
            return data
        else:
            print(f"[ERROR] API returned code {code}: {msg}")
            return None

    except Exception as e:
        print(f"[ERROR] STS token test failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    print("\n" + "=" * 60)
    print("VMOS Cloud API Integration Test")
    print("=" * 60 + "\n")

    if not test_env():
        sys.exit(1)

    result = test_connection()
    if not result:
        print("\n[ERROR] Connection test failed - check credentials")
        sys.exit(1)

    client = result["client"]
    instances = result["instances"]

    sts_result = test_sts_token(client, instances)

    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    if result and sts_result:
        print("[SUCCESS] All tests passed!")
        print("\nVMOS integration is ready for use.")
        print("\nNext steps:")
        print("  1. Use get_client() to get VMOS client")
        print("  2. Use client.get_instance_list() to list devices")
        print("  3. Use client.get_sts_token(pad_code) for SDK token")
    elif result:
        print("[PARTIAL] Connection works, but STS token failed")
    else:
        print("[FAILED] Tests failed - check configuration")

    return 0 if (result and sts_result) else 1


if __name__ == "__main__":
    sys.exit(main())