import type { Meta, StoryObj } from "@storybook/react";
import { MonoId } from "./MonoId";

const meta: Meta<typeof MonoId> = {
  title: "Components/MonoId",
  component: MonoId,
  args: {
    prefix: "evt",
    id: "8f32a1c49e07b2d6f113h409",
    full: "evt-8f32a1c4-9e07-b2d6-f113-h409abcdef12",
    length: 8,
    copyable: true,
    hashFormat: false,
  },
  argTypes: {
    length: { control: { type: "number", min: 4, max: 16, step: 2 } },
  },
};

export default meta;

/** 基线：事件流.html 行 439 evt-8f32（短格式 + 复制 + tooltip 全量） */
export const Default: StoryObj<typeof meta> = {};

export const HashFormat: StoryObj<typeof meta> = {
  args: {
    prefix: undefined,
    id: "a4c19f3d8827b6e5021f9c44d0a8",
    full: "a4c19f3d8827b6e5021f9c44d0a8e77b",
    hashFormat: true,
  },
};

export const NotCopyable: StoryObj<typeof meta> = {
  args: { prefix: "dc", id: "dc-1048-77aa", full: "dc-1048-77aa", copyable: false },
};
