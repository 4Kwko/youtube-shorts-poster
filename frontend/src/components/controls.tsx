import type { ReactNode } from "react";

interface FieldProps {
  label: string;
  hint?: ReactNode;
  children: ReactNode;
}

export function Field({ label, hint, children }: FieldProps) {
  return (
    <div className="field-group">
      <div className="field-group__head">
        <span className="field-group__label">{label}</span>
        {hint && <span className="field-group__hint">{hint}</span>}
      </div>
      {children}
    </div>
  );
}

interface ToggleProps {
  label: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}

export function Toggle({
  label,
  checked,
  disabled = false,
  onChange,
}: ToggleProps) {
  return (
    <label className="toggle">
      <span className="toggle__label">{label}</span>
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className="toggle__track" aria-hidden="true" />
    </label>
  );
}

interface SegmentedProps<T extends string> {
  label: string;
  value: T;
  options: readonly { id: T; name: string }[];
  disabled?: boolean;
  onChange: (value: T) => void;
}

export function Segmented<T extends string>({
  label,
  value,
  options,
  disabled = false,
  onChange,
}: SegmentedProps<T>) {
  return (
    <div
      className="segmented"
      role="radiogroup"
      aria-label={label}
      onKeyDown={(event) => {
        if (
          disabled ||
          !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(
            event.key,
          )
        )
          return;
        event.preventDefault();
        const index = options.findIndex((option) => option.id === value);
        const step = ["ArrowRight", "ArrowDown"].includes(event.key) ? 1 : -1;
        const next = (index + step + options.length) % options.length;
        const option = options[next];
        if (option) onChange(option.id);
        const buttons = event.currentTarget.querySelectorAll<HTMLButtonElement>("button");
        buttons[next]?.focus();
      }}
    >
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          role="radio"
          aria-checked={value === option.id}
          tabIndex={value === option.id ? 0 : -1}
          className="segmented__item"
          disabled={disabled}
          onClick={() => onChange(option.id)}
        >
          {option.name}
        </button>
      ))}
    </div>
  );
}

interface SliderProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  minLabel?: string;
  maxLabel?: string;
  display: string;
  disabled?: boolean;
  onChange: (value: number) => void;
}

export function Slider({
  label,
  value,
  min,
  max,
  step = 1,
  minLabel,
  maxLabel,
  display,
  disabled = false,
  onChange,
}: SliderProps) {
  return (
    <div className="field-group">
      <span className="field-group__label">{label}</span>
      <div className="slider">
        <span className="slider__bound">{minLabel ?? min}</span>
        <input
          type="range"
          aria-label={label}
          min={min}
          max={max}
          step={step}
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(Number(event.target.value))}
        />
        <span className="slider__bound">{maxLabel ?? max}</span>
      </div>
      <p className="slider__value">{display}</p>
    </div>
  );
}

interface ColorsProps {
  label: string;
  value: string;
  presets: readonly string[];
  disabled?: boolean;
  onChange: (value: string) => void;
}

export function ColorChoice({
  label,
  value,
  presets,
  disabled,
  onChange,
}: ColorsProps) {
  return (
    <div className="colors">
      <span className="colors__label">{label}</span>
      <div className="colors__swatches">
        {presets.map((preset) => (
          <button
            key={preset}
            type="button"
            className="swatch"
            style={{ background: preset }}
            aria-label={`${label}: ${preset}`}
            aria-pressed={value.toUpperCase() === preset.toUpperCase()}
            disabled={disabled}
            onClick={() => onChange(preset)}
          />
        ))}
        <input
          type="color"
          className="swatch swatch--picker"
          aria-label={`${label} personalizada`}
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value.toUpperCase())}
        />
      </div>
    </div>
  );
}
