import { FileVideo, Link2, X } from "lucide-react";
import { Button } from "./ui";
import type { QueueItem } from "../lib/queue";
interface Props {
  item: QueueItem;
  index: number;
  disabled: boolean;
  submitting: boolean;
  removing: boolean;
  onRemove: () => void;
}
export function QueueItemRow({
  item,
  index,
  disabled,
  submitting,
  removing,
  onRemove,
}: Props) {
  return (
    <li className={`queue__item ${removing ? "queue__item--removing" : ""}`}>
      <span className="queue__index mono">
        {String(index + 1).padStart(2, "0")}
      </span>
      <span className="queue__kind" aria-hidden="true">
        {item.kind === "file" ? <FileVideo size={17} /> : <Link2 size={17} />}
      </span>
      <span className="queue__body">
        <span className="queue__url" title={item.value}>
          {item.label}
        </span>
        <span className="queue__state">
          {submitting ? "Enviando" : "Aguardando"} ·{" "}
          {item.kind === "file" ? "Arquivo local" : "Link de vídeo"}
        </span>
      </span>
      <Button
        variant="icon"
        aria-label={`Remover ${item.label} da fila`}
        disabled={disabled}
        onClick={onRemove}
      >
        <X size={15} aria-hidden="true" />
      </Button>
    </li>
  );
}
