import { useEffect, useRef } from "react";
import { TriangleAlert } from "lucide-react";
import { Button } from "./ui";
interface Props {
  onCancel: () => void;
  onConfirm: () => void;
}
export function ConfirmDialog({ onCancel, onConfirm }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    const previous = document.activeElement;
    dialog?.showModal();
    return () => {
      dialog?.close();
      if (previous instanceof HTMLElement) previous.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className="dialog"
      aria-labelledby="delete-title"
      aria-describedby="delete-description"
      onCancel={(event) => {
        event.preventDefault();
        onCancel();
      }}
    >
      <div className="dialog__box">
        <TriangleAlert size={24} aria-hidden="true" />
        <h2 id="delete-title">Excluir projeto?</h2>
        <p id="delete-description">
          Isso remove o projeto e os arquivos temporários internos. Os clipes já
          exportados para sua pasta serão mantidos.
        </p>
        <div className="dialog__actions">
          <Button variant="secondary" onClick={onCancel} autoFocus>
            Cancelar
          </Button>
          <Button variant="danger" onClick={onConfirm}>
            Excluir projeto
          </Button>
        </div>
      </div>
    </dialog>
  );
}
