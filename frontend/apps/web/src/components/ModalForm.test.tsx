import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Plus } from "lucide-react";
import { ModalForm } from "./ModalForm";

const BASE_PROPS = {
  title: "注册业务对象",
  icon: <Plus className="w-5 h-5" aria-hidden="true" />,
  onCancel: () => {},
};

describe("ModalForm（antd Modal 封装）", () => {
  it("open 时渲染图标徽标、标题与 children", async () => {
    render(
      <ModalForm {...BASE_PROPS} open submitText="创建对象" onSubmit={() => {}}>
        <input placeholder="例如：客户主数据" />
      </ModalForm>,
    );
    expect(await screen.findByText("注册业务对象")).toBeInTheDocument();
    expect(document.querySelector(".bg-primary-50.text-primary")).not.toBeNull();
    expect(document.querySelector(".lucide-plus")).not.toBeNull();
    expect(screen.getByPlaceholderText("例如：客户主数据")).toBeInTheDocument();
  });

  it("open=false 不渲染内容", () => {
    render(
      <ModalForm {...BASE_PROPS} open={false}>
        <div>NEVER</div>
      </ModalForm>,
    );
    expect(screen.queryByText("注册业务对象")).not.toBeInTheDocument();
    expect(screen.queryByText("NEVER")).not.toBeInTheDocument();
  });

  it("取消与主按钮分别触发 onCancel/onSubmit", async () => {
    const onCancel = vi.fn();
    const onSubmit = vi.fn();
    render(
      <ModalForm {...BASE_PROPS} onCancel={onCancel} open onSubmit={onSubmit} submitText="创建对象">
        body
      </ModalForm>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "取消" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: /创建对象/ }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("缺省 onSubmit：底栏只有取消，无主按钮", async () => {
    render(
      <ModalForm {...BASE_PROPS} open>
        body
      </ModalForm>,
    );
    expect(await screen.findByRole("button", { name: "取消" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "确定" })).not.toBeInTheDocument();
  });

  it("底栏结构与 confirmLoading：border-top + 主按钮 loading 态", async () => {
    render(
      <ModalForm {...BASE_PROPS} open onSubmit={() => {}} submitText="创建对象" confirmLoading>
        body
      </ModalForm>,
    );
    const footer = (await waitFor(() => {
      const el = document.querySelector('[data-dom-id="modal-form-cancel"]');
      expect(el).not.toBeNull();
      return el!.parentElement!;
    }))!;
    expect(footer).toHaveClass("border-t", "justify-end");
    const submit = await screen.findByRole("button", { name: /创建对象/ });
    await waitFor(() => expect(submit).toHaveClass("ant-btn-loading"));
  });
});
