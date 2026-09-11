import { useState } from "react";
import type { FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { LocalOAuthFile } from "@/features/accounts/schemas";

const DEFAULT_OAUTH_FOLDER = String.raw`C:\Retention_Infra\codex-lb\Oauth`;

export type ImportDialogProps = {
  open: boolean;
  busy: boolean;
  error: string | null;
  localFilesAvailable: boolean;
  localFiles: LocalOAuthFile[];
  localFilesLoading: boolean;
  onOpenChange: (open: boolean) => void;
  onImportLocal: (filename: string) => Promise<void>;
  onImport: (file: File) => Promise<void>;
};

export function ImportDialog({
  open,
  busy,
  error,
  localFilesAvailable,
  localFiles,
  localFilesLoading,
  onOpenChange,
  onImportLocal,
  onImport,
}: ImportDialogProps) {
  const { t } = useTranslation();
  const [file, setFile] = useState<File | null>(null);
  const [selectedLocalFile, setSelectedLocalFile] = useState("");

  const activeLocalFile = localFiles.some((item) => item.name === selectedLocalFile)
    ? selectedLocalFile
    : "";

  const reset = () => {
    setFile(null);
    setSelectedLocalFile("");
  };

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) {
      reset();
    }
    onOpenChange(nextOpen);
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!file) {
      return;
    }
    await onImport(file);
    handleOpenChange(false);
  };

  const handleLocalImport = async () => {
    if (!activeLocalFile) {
      return;
    }
    await onImportLocal(activeLocalFile);
    handleOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("accounts.importDialog.title")}</DialogTitle>
          <DialogDescription>{t("accounts.importDialog.description")}</DialogDescription>
        </DialogHeader>

        <form className="space-y-4" onSubmit={handleSubmit}>
          <section className="space-y-3 rounded-lg border bg-muted/20 p-3" aria-labelledby="default-oauth-folder-title">
            <div className="space-y-1">
              <p id="default-oauth-folder-title" className="text-sm font-medium">Default OAuth folder</p>
              <p className="break-all font-mono text-xs text-muted-foreground" title={DEFAULT_OAUTH_FOLDER}>
                {DEFAULT_OAUTH_FOLDER}
              </p>
            </div>

            {localFilesLoading ? (
              <p className="text-xs text-muted-foreground">Checking for JSON files…</p>
            ) : localFilesAvailable && localFiles.length > 0 ? (
              <div className="space-y-2">
                <Label htmlFor="local-auth-json-file">OAuth JSON file</Label>
                <select
                  id="local-auth-json-file"
                  className="h-9 w-full min-w-0 truncate rounded-md border border-input bg-background px-3 text-sm shadow-xs focus-visible:border-ring focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                  value={activeLocalFile}
                  onChange={(event) => setSelectedLocalFile(event.target.value)}
                  disabled={busy}
                >
                  <option value="">Select a JSON file</option>
                  {localFiles.map((item) => (
                    <option key={item.name} value={item.name} title={item.name}>
                      {item.name} ({formatFileSize(item.sizeBytes)})
                    </option>
                  ))}
                </select>
                <Button
                  type="button"
                  className="w-full"
                  disabled={busy || !activeLocalFile}
                  onClick={() => void handleLocalImport()}
                >
                  Import selected file
                </Button>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                {localFilesAvailable
                  ? "No top-level JSON files were found in this folder."
                  : "This folder is not available to the current container."}
              </p>
            )}
          </section>

          <div className="flex items-center gap-3" aria-hidden="true">
            <div className="h-px flex-1 bg-border" />
            <span className="text-xs text-muted-foreground">or upload manually</span>
            <div className="h-px flex-1 bg-border" />
          </div>

          <div className="space-y-2">
            <Label htmlFor="auth-json-file">File from another folder</Label>
            <Input
              id="auth-json-file"
              type="file"
              accept="application/json,.json"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </div>

          {error ? (
            <p className="rounded-md border border-destructive/30 bg-destructive/10 px-2 py-1 text-xs text-destructive">
              {error}
            </p>
          ) : null}

          <DialogFooter>
            <Button type="submit" disabled={busy || !file}>
              Upload and import
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function formatFileSize(sizeBytes: number): string {
  if (sizeBytes < 1024) {
    return `${sizeBytes} B`;
  }
  return `${(sizeBytes / 1024).toFixed(sizeBytes < 10 * 1024 ? 1 : 0)} KiB`;
}
