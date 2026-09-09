import { useRef, type ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {
  X,
  ArrowRight,
  FileText,
  Check,
  Clock,
  LoaderCircle,
  Circle,
  AlertCircle,
} from "lucide-react";
import { Link } from "react-router-dom";
export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={"badge " + tone}>{children}</span>;
}
export function SectionHeader({
  title,
  subtitle,
  to,
  label = "View all",
}: {
  title: string;
  subtitle?: string;
  to?: string;
  label?: string;
}) {
  return (
    <div className="section-head">
      <div>
        <h2>{title}</h2>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {to && (
        <Link className="text-link" to={to}>
          {label} <ArrowRight size={14} />
        </Link>
      )}
    </div>
  );
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <FileText size={26} />
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
export function Modal({
  open,
  onOpenChange,
  title,
  children,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  title: string;
  children: ReactNode;
}) {
  const returnFocus = useRef<HTMLElement | null>(null);
  const wasOpen = useRef(false);
  if (open && !wasOpen.current)
    returnFocus.current = document.activeElement as HTMLElement;
  wasOpen.current = open;
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content
          className="dialog-content"
          aria-describedby={undefined}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            returnFocus.current?.focus();
          }}
        >
          <div className="dialog-heading">
            <Dialog.Title>{title}</Dialog.Title>
            <Dialog.Close className="icon-button" aria-label="Close dialog">
              <X size={18} />
            </Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
export function TaskIcon({ status }: { status: string }) {
  return status === "COMPLETED" ? (
    <Check size={14} className="green" />
  ) : status === "ACTIVE" ? (
    <LoaderCircle size={14} className="spin" />
  ) : status === "BLOCKED" ? (
    <AlertCircle size={14} className="amber" />
  ) : status === "CANCELLED" ? (
    <X size={14} />
  ) : (
    <Circle size={11} className="muted" />
  );
}
export function ScopeMark({
  scope,
  small = false,
}: {
  scope: string;
  small?: boolean;
}) {
  return (
    <span className={"scope-mark " + (small ? "small" : "")}>
      {scope === "NBIS" ? (
        "N"
      ) : scope === "Momentum" ? (
        "M"
      ) : scope === "AI Infra" ? (
        "AI"
      ) : (
        <FileText size={small ? 14 : 20} />
      )}
    </span>
  );
}
export function formatDate(value: string | undefined | null) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Not recorded"
    : new Intl.DateTimeFormat("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      }).format(date);
}
export function StateBadge({ status }: { status: string }) {
  const tone = ["verified", "COMPLETED", "CLOSED", "pass"].includes(status)
    ? "green"
    : ["rejected", "BLOCKED", "fail"].includes(status)
      ? "red"
      : ["unchecked", "weak", "OPEN", "pass_with_caveats", "partial"].includes(
            status,
          )
        ? "amber"
        : "neutral";
  return <Badge tone={tone}>{status.replaceAll("_", " ")}</Badge>;
}
export function Updated({ date }: { date: string }) {
  return (
    <span className="inline-meta">
      <Clock size={12} />
      {formatDate(date)}
    </span>
  );
}
