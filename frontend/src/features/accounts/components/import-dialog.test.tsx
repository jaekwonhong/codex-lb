import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ImportDialog } from "./import-dialog";

function renderDialog(overrides: Partial<React.ComponentProps<typeof ImportDialog>> = {}) {
  const props: React.ComponentProps<typeof ImportDialog> = {
    open: true,
    busy: false,
    error: null,
    localFilesAvailable: true,
    localFiles: [{ name: "team-auth.json", sizeBytes: 2048 }],
    localFilesLoading: false,
    onOpenChange: vi.fn(),
    onImportLocal: vi.fn().mockResolvedValue(undefined),
    onImport: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
  render(<ImportDialog {...props} />);
  return props;
}

describe("ImportDialog", () => {
  it("shows the approved folder as the primary import source", async () => {
    const user = userEvent.setup();
    const props = renderDialog();

    expect(screen.getByText(String.raw`C:\Retention_Infra\codex-lb\Oauth`)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("OAuth JSON file"), "team-auth.json");
    await user.click(screen.getByRole("button", { name: "Import selected file" }));

    expect(props.onImportLocal).toHaveBeenCalledWith("team-auth.json");
    expect(props.onOpenChange).toHaveBeenCalledWith(false);
  });

  it("keeps manual upload available when the default folder is unavailable", async () => {
    const user = userEvent.setup();
    const file = new File(["{}"], "manual.json", { type: "application/json" });
    const props = renderDialog({ localFilesAvailable: false, localFiles: [] });

    expect(screen.getByText("This folder is not available to the current container.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("File from another folder"), { target: { files: [file] } });
    await user.click(screen.getByRole("button", { name: "Upload and import" }));

    expect(props.onImport).toHaveBeenCalledWith(file);
  });

  it("distinguishes an available but empty folder", () => {
    renderDialog({ localFiles: [] });

    expect(screen.getByText("No top-level JSON files were found in this folder.")).toBeInTheDocument();
    expect(screen.getByLabelText("File from another folder")).toBeEnabled();
  });
});
