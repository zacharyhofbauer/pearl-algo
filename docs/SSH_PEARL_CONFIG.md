# SSH host "pearl" for Cursor Remote

Use the short host name **pearl** to connect to the PearlAlgo server from Cursor (Remote-SSH), distinct from the project folder name **PearlAlgoProject**.

**On the machine where you run Cursor** (your laptop/desktop), edit `~/.ssh/config` and add:

```
Host pearl
    HostName 100.100.12.86
    User pearl
```

Add `IdentityFile ~/.ssh/id_ed25519` (or your key path) if you use a specific key for this server.

Then in Cursor: **Remote-SSH: Connect to Host…** → choose **pearl** → open folder **/home/pearl/PearlAlgoProject**.
