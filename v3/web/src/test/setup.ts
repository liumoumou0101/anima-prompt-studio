import "@testing-library/jest-dom/vitest";
import {cleanup} from "@testing-library/react";
import {afterEach} from "vitest";

afterEach(() => cleanup());

// jsdom has dialog elements but no top-layer lifecycle; real browsers supply it.
if (!HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function () {this.open = true;};
  HTMLDialogElement.prototype.close = function () {this.open = false; this.dispatchEvent(new Event("close"));};
}
