using System;
using System.IO;
using System.Text;

public sealed class Mk1BoundedLog : IDisposable {
    readonly string folder, name;
    readonly long limit;
    readonly int slots;
    readonly UTF8Encoding utf8 = new UTF8Encoding(false);
    FileStream stream;
    int index;
    public long Dropped { get; private set; }
    public long Rotations { get; private set; }
    public Mk1BoundedLog(string directory, string stem, long maximumBytes, int retainedSlots) {
        if (maximumBytes < 128 || retainedSlots < 1 || retainedSlots > 4) throw new ArgumentOutOfRangeException();
        folder = Path.GetFullPath(directory); name = stem; limit = maximumBytes; slots = retainedSlots;
        Open(true);
    }
    void Open(bool first) {
        string path = Path.Combine(folder, slots == 1 ? name + ".jsonl" : name + "-" + index + ".jsonl");
        if (Path.GetDirectoryName(Path.GetFullPath(path)) != folder) throw new IOException("Log outside session directory");
        if (File.Exists(path) && (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) throw new IOException("Linked log refused");
        stream = new FileStream(path, first ? FileMode.CreateNew : FileMode.Create, FileAccess.Write, FileShare.Read);
    }
    public bool Write(string json) {
        byte[] data = utf8.GetBytes(json + "\n");
        if (data.Length > limit) { Dropped++; return false; }
        if (stream.Length + data.Length > limit) {
            if (slots == 1) { Dropped++; return false; }
            stream.Dispose(); index = (index + 1) % slots; Rotations++; Open(false);
        }
        stream.Write(data, 0, data.Length); stream.Flush(); return true;
    }
    public void Dispose() { if (stream != null) { stream.Dispose(); stream = null; } }
}
