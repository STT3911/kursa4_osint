"""Quick live test for Sherlock and Snoop — run with venv python."""
import sys
import time

def test_sherlock(username: str = "github", timeout: int = 40) -> None:
    from sherlock_integration import run_sherlock, is_sherlock_available
    if not is_sherlock_available():
        print("Sherlock: NOT AVAILABLE")
        return
    print(f"Sherlock: testing @{username} (timeout={timeout}s)...")
    t = time.time()
    try:
        results = run_sherlock(username, timeout=timeout)
        print(f"Sherlock OK: {len(results)} accounts in {time.time()-t:.1f}s")
        for r in results[:5]:
            print(f"  [{r['site_name']}] {r['profile_url']}")
    except Exception as e:
        print(f"Sherlock ERROR ({time.time()-t:.1f}s): {type(e).__name__}: {e}")

def test_snoop(username: str = "github", timeout: int = 40) -> None:
    from snoop_integration import run_snoop, is_snoop_available
    if not is_snoop_available():
        print("Snoop: NOT AVAILABLE")
        return
    print(f"Snoop: testing @{username} (timeout={timeout}s)...")
    t = time.time()
    try:
        results = run_snoop(username, timeout=timeout)
        print(f"Snoop OK: {len(results)} accounts in {time.time()-t:.1f}s")
        for r in results[:5]:
            print(f"  [{r['site_name']}] {r['profile_url']}")
    except Exception as e:
        print(f"Snoop ERROR ({time.time()-t:.1f}s): {type(e).__name__}: {e}")

if __name__ == "__main__":
    username = sys.argv[1] if len(sys.argv) > 1 else "github"
    test_sherlock(username)
    print()
    test_snoop(username)
