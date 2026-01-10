import { useState } from "react";
import { Upload, File, Trash2, FileText, Image, FileSpreadsheet } from "lucide-react";
import { DashboardLayout } from "@/components/layout/DashboardLayout";
import { Button } from "@/components/ui/button";
import { toast } from "@/hooks/use-toast";

interface UploadedFile {
  id: string;
  name: string;
  size: string;
  type: string;
  uploadedAt: string;
}

const mockFiles: UploadedFile[] = [
  { id: "1", name: "contacts-2024.csv", size: "2.4 MB", type: "csv", uploadedAt: "Dec 12, 2024" },
  { id: "2", name: "call-script.txt", size: "12 KB", type: "text", uploadedAt: "Dec 11, 2024" },
  { id: "3", name: "product-catalog.pdf", size: "5.8 MB", type: "pdf", uploadedAt: "Dec 10, 2024" },
];

const fileIcons: Record<string, React.ComponentType<{ className?: string }>> = {
  csv: FileSpreadsheet,
  text: FileText,
  pdf: File,
  image: Image,
};

export default function CustomData() {
  const [files, setFiles] = useState<UploadedFile[]>(mockFiles);
  const [dragActive, setDragActive] = useState(false);

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFiles(e.dataTransfer.files);
    }
  };

  const handleFiles = (fileList: FileList) => {
    const newFiles: UploadedFile[] = Array.from(fileList).map((file, index) => ({
      id: `new-${Date.now()}-${index}`,
      name: file.name,
      size: formatFileSize(file.size),
      type: getFileType(file.name),
      uploadedAt: new Date().toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }),
    }));

    setFiles((prev) => [...newFiles, ...prev]);
    toast({ title: "Files Uploaded", description: `${fileList.length} file(s) uploaded successfully` });
  };

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  };

  const getFileType = (filename: string): string => {
    const ext = filename.split(".").pop()?.toLowerCase() || "";
    if (["csv", "xlsx", "xls"].includes(ext)) return "csv";
    if (["txt", "md"].includes(ext)) return "text";
    if (["jpg", "jpeg", "png", "gif", "webp"].includes(ext)) return "image";
    return "pdf";
  };

  const handleDelete = (id: string) => {
    setFiles((prev) => prev.filter((f) => f.id !== id));
    toast({ title: "File Deleted", description: "File has been removed" });
  };

  return (
    <DashboardLayout>
      <div className="max-w-4xl">
        <header className="mb-8">
          <h1 className="text-3xl font-bold text-foreground">Custom Data</h1>
          <p className="text-muted-foreground mt-2">
            Upload and manage your custom files and data
          </p>
        </header>

        {/* Upload Zone */}
        <div
          className={`bg-card rounded-2xl shadow-card p-8 mb-8 border-2 border-dashed transition-colors ${
            dragActive ? "border-primary bg-accent/30" : "border-border"
          }`}
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
        >
          <div className="text-center">
            <input
              type="file"
              multiple
              onChange={(e) => e.target.files && handleFiles(e.target.files)}
              className="hidden"
              id="file-upload"
            />
            <label htmlFor="file-upload" className="cursor-pointer">
              <div className="h-16 w-16 mx-auto rounded-full bg-accent flex items-center justify-center mb-4">
                <Upload className="h-8 w-8 text-muted-foreground" />
              </div>
              <p className="text-lg font-medium text-card-foreground mb-2">
                Drop files here or click to upload
              </p>
              <p className="text-sm text-muted-foreground">
                Support for CSV, TXT, PDF, Images, and more
              </p>
            </label>
          </div>
        </div>

        {/* File List */}
        <div className="bg-card rounded-2xl shadow-card overflow-hidden">
          <div className="p-6 border-b border-border">
            <h2 className="font-semibold text-card-foreground">Uploaded Files</h2>
            <p className="text-sm text-muted-foreground">{files.length} files</p>
          </div>
          {files.length === 0 ? (
            <div className="p-8 text-center">
              <p className="text-muted-foreground">No files uploaded yet</p>
            </div>
          ) : (
            <div className="divide-y divide-border">
              {files.map((file) => {
                const IconComponent = fileIcons[file.type] || File;
                return (
                  <div
                    key={file.id}
                    className="p-4 flex items-center gap-4 hover:bg-accent/30 transition-colors"
                  >
                    <div className="h-10 w-10 rounded-lg bg-accent flex items-center justify-center flex-shrink-0">
                      <IconComponent className="h-5 w-5 text-muted-foreground" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-card-foreground truncate">{file.name}</p>
                      <p className="text-sm text-muted-foreground">
                        {file.size} · {file.uploadedAt}
                      </p>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => handleDelete(file.id)}
                      className="text-muted-foreground hover:text-destructive"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </DashboardLayout>
  );
}