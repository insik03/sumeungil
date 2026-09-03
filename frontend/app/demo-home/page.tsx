import type { Metadata } from "next";
import DemoHome from "../../components/demo-home/DemoHome";

export const metadata: Metadata = {
  title: "숨은길 홈 데모 — 붐비는 길 옆, 진짜 여행",
  description: "과밀 관광지를 한적한 대안 코스로 바꾸는 숨은길 홈 데모입니다.",
};

export default function DemoHomePage() {
  return <DemoHome />;
}
