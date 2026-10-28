# Ubuntu on this Windows laptop

**Installation is paused.** The attempted WSL commands did not complete installation.
No working Ubuntu or ROS runtime has been verified on this laptop. Because the next
motor test uses Windows, finish that test before changing the development environment
if keeping the machine stable for the demonstration is the priority.

## What changes and what can go wrong?

WSL 2 is Microsoft's supported way to run Linux alongside Windows. It enables Windows
virtualization features and installs Linux in a virtual disk. It does not intentionally
replace Windows or repartition your drive. A restart may be required. Save work and
back up important files before installation, as with other system changes.

It consumes disk space, and running Linux/builds consumes RAM and CPU. Limits can be
configured later. Linux can access Windows files through `/mnt/c`, so a mistaken Linux
file command can also affect Windows files. Treat it as another development environment,
not an isolated safety box. USB controllers and network discovery need separate testing.

References: [Microsoft installation guide](https://learn.microsoft.com/en-us/windows/wsl/install),
[WSL FAQ and file access](https://learn.microsoft.com/en-us/windows/wsl/faq),
[resource configuration](https://learn.microsoft.com/en-us/windows/wsl/wsl-config).

## Install when ready

1. Save open work. Open **PowerShell as administrator** and run:

   ```powershell
   wsl --install -d Ubuntu-24.04 --no-launch
   ```

   If it asks for a restart, restart when your work is saved. If it fails, retain the
   exact error for diagnosis; do not delete distributions or reset Windows features.
2. Open Ubuntu 24.04 from Start and create your Linux username/password. Password typing
   is not displayed. Keep the password private. Confirm the release inside Ubuntu:

   ```bash
   cat /etc/os-release
   ```

   In PowerShell, `wsl --list --verbose` should show Ubuntu-24.04 using version **2**.
3. Install Microsoft's **WSL** extension in your existing Windows VS Code. Open an
   Ubuntu terminal and open the Linux project with `code .`. The VS Code corner should
   show a WSL connection; use Linux `/usr/bin/python3`, not Windows Anaconda.

   [VS Code WSL instructions](https://code.visualstudio.com/docs/remote/wsl).

## Copy the prepared project into Linux

The newly prepared ROS files may still be uncommitted locally, so cloning GitHub alone
may not include them. This first-copy command includes the current local files and
refuses to overwrite an existing Linux project:

```bash
mkdir -p ~/projects
if [ -e ~/projects/C2 ]; then
  echo 'C2 already exists. Open it and reconcile changes; do not overwrite it.'
else
  cp -a '/mnt/c/Users/Cutle/Documents/School/Fall 2026/URC/C2-team' ~/projects/C2
fi
cd ~/projects/C2
code .
```

Use the Linux copy for future ROS work. It is a separate copy: edits will not
automatically appear in the original Windows folder. Coordinate commits/branches
before switching between copies. Keep the Windows bench copy for the motor test.

## Install ROS 2 Jazzy, then build

Follow the official [Jazzy Ubuntu deb installation guide](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html)
to set locale, enable the ROS apt repository and install `ros-jazzy-ros-base` and
`ros-dev-tools`. Ubuntu must report version 24.04. Installing just a Python package
named ROS is not equivalent. Do not use Windows Anaconda for this workspace.

Once that repository is configured, install the project dependencies in Ubuntu:

```bash
sudo apt update
sudo apt install python3-tk python3-pygame python3-pytest python3-colcon-common-extensions ros-jazzy-rosidl-default-generators
```

Then follow [build, test and launch commands](../ros2_ws/README.md).

## Controller and router are separate integration steps

Start with sliders: no USB controller forwarding is needed for that mock test.
The Xbox controller working in Windows does **not** mean Ubuntu can see it. WSL USB
access may require `usbipd-win` and attaching the device to Linux. Attachment can
remove the device from Windows until detached. Do this after the Windows motor test.
See [Microsoft's USB guide](https://learn.microsoft.com/en-us/windows/wsl/connect-usb).

WSL normally uses NAT networking. ROS discovery between separate machines may need
additional network configuration; supported Windows 11 setups offer mirrored
networking. Test local mock first, then two-machine mock on the actual router.
Do not broadly disable firewalls to make discovery work. See
[Microsoft's networking guide](https://learn.microsoft.com/en-us/windows/wsl/networking).

Native Ubuntu remains an option if USB/network behavior becomes a persistent obstacle.
Dual boot, repartitioning, and USB driver installation are not part of the current changes.
