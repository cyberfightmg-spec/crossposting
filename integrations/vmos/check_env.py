import os
import sys


def check_vmos_env():
    required_vars = {
        "VMOS_HOST": "API host",
        "VMOS_AK": "Access Key ID",
        "VMOS_SK": "Secret Access Key",
    }
    optional_vars = {
        "VMOS_CALLBACK_URL": "Callback URL (optional)",
    }

    missing = []
    present = []

    for var, description in required_vars.items():
        value = os.environ.get(var)
        if value is None or value == "" or value.startswith("PASTE_"):
            missing.append(var)
        else:
            present.append(f"{var} (set, {len(value)} chars)")

    for var, description in optional_vars.items():
        value = os.environ.get(var)
        if value:
            present.append(f"{var} (set)")

    print("=" * 50)
    print("VMOS Environment Check")
    print("=" * 50)

    if present:
        print("\n[OK] Present variables:")
        for p in present:
            print(f"  - {p}")

    if missing:
        print("\n[FAIL] Missing or not configured:")
        for m in missing:
            print(f"  - {m}")
        print("\nPlease add these to .env file:")
        print("  VMOS_HOST=https://api.vmoscloud.com")
        print("  VMOS_AK=YOUR_ACCESS_KEY_ID")
        print("  VMOS_SK=YOUR_SECRET_ACCESS_KEY")
        print("  VMOS_CALLBACK_URL=https://your-callback-url.com (optional)")
        return False

    print("\n[OK] All required variables are configured!")
    return True


def check_vmos_env(stop_on_missing=False):
    """Check VMOS environment variables.
    
    Args:
        stop_on_missing: If True, exit with error code when variables are missing.
                       If False (default), just warn but continue.
    """
    required_vars = {
        "VMOS_HOST": "API host",
        "VMOS_AK": "Access Key ID",
        "VMOS_SK": "Secret Access Key",
    }
    optional_vars = {
        "VMOS_CALLBACK_URL": "Callback URL (optional)",
    }

    missing = []
    present = []

    for var, description in required_vars.items():
        value = os.environ.get(var)
        if value is None or value == "" or value.startswith("PASTE_"):
            missing.append(var)
        else:
            present.append(f"{var} (set, {len(value)} chars)")

    for var, description in optional_vars.items():
        value = os.environ.get(var)
        if value:
            present.append(f"{var} (set)")

    print("=" * 50)
    print("VMOS Environment Check")
    print("=" * 50)

    if present:
        print("\n[OK] Present variables:")
        for p in present:
            print(f"  - {p}")

    if missing:
        print("\n[FAIL] Missing or not configured:")
        for m in missing:
            print(f"  - {m}")
        print("\nPlease add these to .env file:")
        print("  VMOS_HOST=https://api.vmoscloud.com")
        print("  VMOS_AK=YOUR_ACCESS_KEY_ID")
        print("  VMOS_SK=YOUR_SECRET_ACCESS_KEY")
        print("  VMOS_CALLBACK_URL=https://your-callback-url.com (optional)")
        
        if stop_on_missing:
            return False
        else:
            print("\n[WARNING] Continuing anyway for testing purposes...")

    if not missing:
        print("\n[OK] All required variables are configured!")
        
    return True


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    success = check_vmos_env(stop_on_missing=True)
    sys.exit(0 if success else 1)