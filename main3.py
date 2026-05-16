import os
import shutil
import subprocess
import sys


def run_adb_cmd(cmd_list):
    """Executes a basic configuration ADB command and returns text output."""
    try:
        if cmd_list[0] != "adb":
            cmd_list.insert(0, "adb")
        result = subprocess.run(
            cmd_list, capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error executing command {' '.join(cmd_list)}: {e.stderr.strip()}")
        return None


def verify_environment():
    """Validates that adb is installed and a device is connected."""
    if not shutil.which("adb"):
        print("Error: 'adb' executable not found in system PATH.")
        sys.exit(1)

    devices = run_adb_cmd(["devices"])
    if not devices:
        print("Error: ADB service failed to respond.")
        sys.exit(1)

    lines = devices.split("\n")[1:]
    connected_devices = [line for line in lines if line.strip() and "device" in line]

    if not connected_devices:
        print("Error: No Android devices found. Ensure USB debugging is active.")
        sys.exit(1)

    print(f"Connected device verified: {connected_devices[0].split()[0]}")


def get_installed_packages():
    """Fetches a list of all installed packages on the device."""
    print("Fetching third-party packages from device...")
    # Filtering by '-3' to limit results to third-party apps for faster navigation
    raw_output = run_adb_cmd(["shell", "pm", "list", "packages", "-3"])
    
    if not raw_output:
        print("No third-party packages found. Fetching all packages...")
        raw_output = run_adb_cmd(["shell", "pm", "list", "packages"])
        
    if not raw_output:
        return []

    packages = []
    for line in raw_output.split("\n"):
        if line.startswith("package:"):
            packages.append(line.replace("package:", "").strip())
    
    return sorted(packages)


def select_package_interactive():
    """Interactive loop to select or search a package name."""
    packages = get_installed_packages()
    
    if not packages:
        print("No packages could be retrieved from the device.")
        user_input = input("Manually enter target package name: ").strip()
        return user_input

    while True:
        print(f"\nFound {len(packages)} packages on the device.")
        print("[1] View all packages")
        print("[2] Search/Filter packages")
        print("[3] Type package name manually")
        
        choice = input("Select an option (1-3): ").strip()
        
        if choice == "1":
            for idx, pkg in enumerate(packages, 1):
                print(f"  [{idx}] {pkg}")
            
            pkg_choice = input("\nSelect package number (or 'b' to go back): ").strip()
            if pkg_choice.lower() == 'b':
                continue
            try:
                idx_sel = int(pkg_choice) - 1
                if 0 <= idx_sel < len(packages):
                    return packages[idx_sel]
            except ValueError:
                pass
            print("Invalid selection.")
            
        elif choice == "2":
            keyword = input("Enter search keyword (case-insensitive): ").strip().lower()
            filtered = [p for p in packages if keyword in p.lower()]
            
            if not filtered:
                print("No matching packages found.")
                continue
                
            print(f"\nMatches for '{keyword}':")
            for idx, pkg in enumerate(filtered, 1):
                print(f"  [{idx}] {pkg}")
                
            pkg_choice = input("\nSelect package number (or 'b' to go back): ").strip()
            if pkg_choice.lower() == 'b':
                continue
            try:
                idx_sel = int(pkg_choice) - 1
                if 0 <= idx_sel < len(filtered):
                    return filtered[idx_sel]
            except ValueError:
                pass
            print("Invalid selection.")
            
        elif choice == "3":
            user_input = input("Enter full package name: ").strip()
            if user_input:
                return user_input
        else:
            print("Invalid option. Please choose 1, 2, or 3.")


def extract_apk(package_name, output_dir):
    """Locates and pulls the base APK of the target package."""
    print(f"\n--- Step 1: Extracting APK for {package_name} ---")

    path_output = run_adb_cmd(["shell", "pm", "path", package_name])
    if not path_output:
        print(f"Failed to find path for package: {package_name}")
        return False

    apk_remote_path = path_output.replace("package:", "").strip()
    local_apk_name = os.path.join(output_dir, f"{package_name}.apk")

    print(f"Pulling APK file to: {local_apk_name}")
    pull_result = run_adb_cmd(["pull", apk_remote_path, local_apk_name])

    if pull_result is not None and os.path.exists(local_apk_name):
        print("Success: APK pulled.")
        return True
    return False


def extract_debug_data(package_name, output_dir):
    """Extracts internal app data using the run-as sandbox context wrapper."""
    print(f"\n--- Step 2: Extracting Debug App Data via 'run-as' ---")
    local_tar_path = os.path.join(output_dir, f"{package_name}_data.tar")

    exec_cmd = ["adb", "exec-out", "run-as", package_name, "tar", "c", "."]
    print(f"Streaming data directory from sandbox for {package_name}...")

    try:
        with open(local_tar_path, "wb") as tar_file:
            process_result = subprocess.run(
                exec_cmd, stdout=tar_file, stderr=subprocess.PIPE, check=True
            )

        if process_result.stderr:
            err_msg = process_result.stderr.decode(errors="ignore").strip()
            if err_msg:
                print(f"Device engine reported an error:\n{err_msg}")
                if "is not debuggable" in err_msg:
                    print(
                        "\n[CRITICAL FAILURE]: This build is not compiled as debuggable."
                    )
                return False

        if os.path.exists(local_tar_path) and os.path.getsize(local_tar_path) > 0:
            print(f"Success! Clean data archive created at: {local_tar_path}")
            print(f"You can extract this file natively using: tar -xf {local_tar_path}")
            return True
        else:
            print("Extraction completed, but the resulting file payload is empty.")
            return False

    except subprocess.CalledProcessError as e:
        print(f"Pipeline execution failed: {e}")
        if os.path.exists(local_tar_path):
            os.remove(local_tar_path)
        return False


if __name__ == "__main__":
    print("========================================")
    print("  Interactive Android Data Extractor    ")
    print("========================================\n")
    
    # 1. Verify environment first
    verify_environment()
    
    # 2. Dynamically choose target package
    TARGET_PACKAGE = select_package_interactive()
    print(f"\nSelected Target: {TARGET_PACKAGE}")
    
    # 3. Choose output directory
    default_dir = "./debug_extracted_data"
    user_dir = input(f"Enter output directory path [Default: {default_dir}]: ").strip()
    OUTPUT_DIRECTORY = user_dir if user_dir else default_dir

    os.makedirs(OUTPUT_DIRECTORY, exist_ok=True)

    # 4. Perform executions
    apk_status = extract_apk(TARGET_PACKAGE, OUTPUT_DIRECTORY)
    data_status = extract_debug_data(TARGET_PACKAGE, OUTPUT_DIRECTORY)

    print("\n--- Execution Summary ---")
    if apk_status and data_status:
        print(
            f"Extraction cycle finished successfully. Components inside '{OUTPUT_DIRECTORY}'."
        )
    else:
        print(
            "Extraction cycle finished with partial or total errors. Review logs above."
        )