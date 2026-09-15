import time
from playwright.sync_api import sync_playwright

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        
        # 1. Main Dashboard Overview
        page.goto("http://localhost:8080")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        page.screenshot(path="screenshots/01_dashboard_pipeline.png")
        print("Screenshot 1 captured: 01_dashboard_pipeline.png")

        # 2. Scenarios Modal
        page.click("#btn-preview-scenarios")
        time.sleep(0.8)
        page.screenshot(path="screenshots/02_scenarios_modal.png")
        print("Screenshot 2 captured: 02_scenarios_modal.png")
        page.click("#modal-scenarios .modal-close-btn")
        time.sleep(0.5)

        # 3. High severity claim with Human-in-the-Loop Banner
        # Trigger the Highway Multi-Collision scenario
        page.evaluate("selectScenario('multi-collision')")
        time.sleep(3.5) # Wait for simulation steps to finish and banner to reveal
        page.screenshot(path="screenshots/03_human_in_the_loop.png")
        print("Screenshot 3 captured: 03_human_in_the_loop.png")

        # 4. Agent Inspector Drawer open
        page.click("#node-reviewer")
        time.sleep(0.8)
        page.screenshot(path="screenshots/04_agent_inspector.png")
        print("Screenshot 4 captured: 04_agent_inspector.png")
        page.click("#inspector-drawer .modal-close-btn")
        time.sleep(0.5)

        # 5. New Claim Modal Form
        page.click("#btn-run-dashboard")
        time.sleep(0.8)
        page.screenshot(path="screenshots/05_new_claim_form.png")
        print("Screenshot 5 captured: 05_new_claim_form.png")

        browser.close()
    print("All screenshots generated successfully!")

if __name__ == "__main__":
    run()
