import streamlit as st
import os
import subprocess
import sys
import json
import socket
import pandas as pd
import numpy as np
from jinja2 import Environment, FileSystemLoader

# ==========================================
# 1. HELPER FUNCTIONS
# ==========================================

def get_bundled_path(relative_path):
    """Allows the app to find bundled templates when compiled with PyInstaller"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def read_file(filepath):
    """Safely read a file to display in the UI"""
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as file:
            return file.read()
    return f"Error: File not found at '{filepath}'."

def check_ip_reachable(ip, port=22, timeout=3):
    """Check if the Bastion IP is reachable via SSH (Port 22)"""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False

# ==========================================
# 2. EXCEL TO JSON CONVERTER
# ==========================================
def convert_custom_excel_to_json(excel_path, output_json_path):
    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"The input file '{excel_path}' was not found.")
    xls = pd.ExcelFile(excel_path)
    combined_data = {}
    for sheet_name in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
        df.replace(r'^\s*$', np.nan, regex=True, inplace=True)
        
        param_name_idx = df.index[df[0] == 'Parameter Name'].tolist()
        host_name_idx = df.index[df[0] == 'Host_Name'].tolist()
        
        if not host_name_idx:
            continue
            
        start_idx = param_name_idx[0] if param_name_idx else 0
        split_idx = host_name_idx[0]
        sheet_json_data = {}
        
        # Section 1: Parameters
        section1_df = df.iloc[start_idx:split_idx]
        section1_df = section1_df.dropna(how='all')
        
        for index, row in section1_df.iterrows():
            key = row[0]
            value = row[1]
            if pd.notna(key) and key != 'Parameter Name':
                sheet_json_data[str(key).strip()] = str(value).strip() if pd.notna(value) else ""
        
        # Section 2: Hosts
        section2_df = df.iloc[split_idx+1:].copy()
        section2_df.columns = df.iloc[split_idx]
        section2_df = section2_df.loc[:, section2_df.columns.notna()]
        section2_df = section2_df.dropna(how='all')
        section2_df = section2_df.fillna("")
        
        hosts_list = section2_df.to_dict(orient='records')
        sheet_json_data['Hosts'] = hosts_list
        combined_data[sheet_name] = sheet_json_data
        
    os.makedirs(os.path.dirname(output_json_path), exist_ok=True)
    with open(output_json_path, 'w', encoding='utf-8') as json_file:
        json.dump(combined_data, json_file, indent=4, default=str)

# ==========================================
# 3. SERVER CONFIGURATION GENERATOR
# ==========================================
def generate_server_config_yaml(json_input_file, yaml_output_file):
    if not os.path.exists(json_input_file):
        raise FileNotFoundError(f"Input file {json_input_file} not found.")

    with open(json_input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    config_vars = data.get("OCP_Instalation_Input", {})
    if not config_vars:
        raise ValueError("The key 'OCP_Instalation_Input' was not found in the JSON file.")

    required_keys = [
        "Base_Domain", "Worker_Count", "Cluster_Name", "Cluster_Network_ipv4", 
        "Machine_Network_ipv4", "Machine_Network_Subnet_ipv4", "Service_Network_ipv4", 
        "api_vip_ipv4", "ingress_vip_ipv4", "pullsecret", "sshKey"
    ]
    
    missing_parameters = []
    for key in required_keys:
        value = config_vars.get(key)
        if value is None or str(value).strip() == "":
            missing_parameters.append(key)
            
    if missing_parameters:
        raise ValueError(f"Missing required Parameters in input sheet: {', '.join(missing_parameters)}")

    env = Environment(loader=FileSystemLoader(get_bundled_path('bastion')))
    template = env.get_template("server.j2")
    rendered_yaml = template.render(OCP_Instalation_Input=config_vars)

    os.makedirs(os.path.dirname(yaml_output_file), exist_ok=True)
    with open(yaml_output_file, 'w', encoding='utf-8') as f:
        f.write(rendered_yaml)

# ==========================================
# 4. BASTION CONFIGURATION GENERATOR
# ==========================================
def generate_bastion_config_yaml(json_input_file, yaml_output_file):
    if not os.path.exists(json_input_file):
        raise FileNotFoundError(f"Input file {json_input_file} not found.")

    with open(json_input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    config_vars = data.get("OCP_Instalation_Input", {})
    if not config_vars:
        raise ValueError("The key 'OCP_Instalation_Input' was not found in the JSON file.")

    env = Environment(loader=FileSystemLoader(get_bundled_path('bastion')))
    template = env.get_template("bastion.j2")
    rendered_yaml = template.render(OCP_Instalation_Input=config_vars)

    os.makedirs(os.path.dirname(yaml_output_file), exist_ok=True)
    with open(yaml_output_file, 'w', encoding='utf-8') as f:
        f.write(rendered_yaml)

# ==========================================
# 6. STREAMLIT UI MAIN APP
# ==========================================
def main():
    if 'pipeline_completed' not in st.session_state:
        st.session_state.pipeline_completed = False
    if 'hardware_type' not in st.session_state:
        st.session_state.hardware_type = "Virtual"
    if 'show_ai_deploy' not in st.session_state:
        st.session_state.show_ai_deploy = False

    st.set_page_config(page_title="Bastion Orchestrator", layout="centered")

    st.title("🚀 Bastion Node Configuration Orchestrator")
    st.markdown("""
    ### How this tool works:
    1. **Browse and Upload:** Select your Cloud CIQ Configuration Excel file (.xlsx).
    2. **Execute Pipeline:** Convert Excel into structured JSON and render configuration files based on Hardware Type (`Virtual` -> generate both `bastion-config.yaml` and `server-config.yaml`; non-Virtual -> `bastion-config.yaml` only).
    3. **Deploy:** Review rendered configurations and deploy directly to the Bastion host via Ansible.
    ---
    """)

    uploaded_file = st.file_uploader("**Select the Configuration Excel File (.xlsx)**", type=["xlsx", "xls"])

    if uploaded_file is not None:
        if st.button(f"▶️ Process File **{uploaded_file.name}**", type="primary"):
            try:
                # Directory Setup inside bastion/temp
                target_folder = os.path.join(os.getcwd(), "bastion", "temp")
                os.makedirs(target_folder, exist_ok=True)
                
                excel_path = os.path.join(target_folder, "bastion-input.xlsx")
                json_path = os.path.join(target_folder, "bastion-input.json")
                server_config_path = os.path.join(target_folder, "server-config.yaml")
                bastion_config_path = os.path.join(target_folder, "bastion-config.yaml")
                
                # Step 1: Save Uploaded File
                with st.spinner("Saving Excel file locally..."):
                    with open(excel_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                
                # Step 2: Convert Excel to JSON
                with st.spinner("Converting Excel data to JSON..."):
                    convert_custom_excel_to_json(excel_path, json_path)

                # Step 3: Read Hardware Type to determine generation logic
                with open(json_path, "r", encoding="utf-8") as json_file:
                    ocp_data = json.load(json_file)
                    hw_type = str(
                        ocp_data.get("OCP_Instalation_Input", {}).get("Hardware_Type", "Virtual")
                    ).strip()
                    st.session_state.hardware_type = hw_type

                is_virtual = hw_type.lower() == "virtual"

                # Step 4: Generate bastion-config.yaml (Always)
                with st.spinner("Generating bastion-config.yaml..."):
                    generate_bastion_config_yaml(json_path, bastion_config_path)

                # Step 5: Conditional Generation based on Hardware Type (Virtual = Both, Non-Virtual = Bastion only)
                if is_virtual:
                    with st.spinner("Generating server-config.yaml..."):
                        generate_server_config_yaml(json_path, server_config_path)
                else:
                    # Clean up old server-config.yaml if present from a previous run
                    if os.path.exists(server_config_path):
                        os.remove(server_config_path)

                st.session_state.pipeline_completed = True
                st.session_state.show_ai_deploy = False 
                
                st.success(f"🎉 Pipeline Completed! Hardware Type: **{hw_type}**.")
                
            except Exception as e:
                st.error(f"❌ An error occurred during execution:\n\n{e}")
    if st.session_state.pipeline_completed:
        if str(st.session_state.get("hardware_type", "")).strip().lower() == "virtual":
            with st.expander("👀 Review your server-config.yaml file"):
                st.code(read_file("bastion/temp/server-config.yaml"), language='yaml')

        with st.expander("👀 Review your bastion-config.yaml file"):
            st.code(read_file("bastion/temp/bastion-config.yaml"), language='yaml')                
       # --- UI STEP 3: Automated Background Deployment ---
        if st.button("🤖 Would you prefer the AI-Agent to configure the Bastion Node automatically?", type="primary"):
            st.session_state.show_ai_deploy = True

        if st.session_state.show_ai_deploy:
            st.markdown("#### 🖥️ Review the Bastion Detail")
            
            json_input_path = os.path.join("bastion", "temp", "bastion-input.json")
            
            # Default fallback credentials
            extracted_ip = ""
            extracted_port = 22
            extracted_user = ""
            extracted_pass = ""

            # Step 1: Parse bastion details from JSON input file
            if os.path.exists(json_input_path):
                try:
                    with open(json_input_path, "r", encoding="utf-8") as jf:
                        json_data = json.load(jf)
                        bastion_str = json_data.get("OCP_Instalation_Input", {}).get("bastion_ip_port_user_password", "").strip()
                        
                        # Expected format: "IP PORT USER PASSWORD"
                        parts = bastion_str.split()
                        if len(parts) >= 4:
                            extracted_ip = parts[0]
                            extracted_port = int(parts[1])
                            extracted_user = parts[2]
                            extracted_pass = " ".join(parts[3:])  # Handles passwords containing spaces
                except Exception as e:
                    st.warning(f"⚠️ Could not parse Bastion credentials from JSON: {e}")

            # Step 2: Render form with values pre-populated from JSON
            with st.form("bastion_form"):
                bastion_ip = st.text_input("Bastion IP Address", value=extracted_ip, placeholder="e.g., 172.20.4.24")
                bastion_port = st.number_input("SSH Port", value=extracted_port, min_value=1, max_value=65535)
                bastion_user = st.text_input("SSH Username", value=extracted_user, placeholder="e.g., root")
                bastion_pass = st.text_input("SSH Password", value=extracted_pass, type="password")
                
                deploy_btn = st.form_submit_button("🔥 Configure Bastion Node", type="primary")
                
                if deploy_btn:
                    if not bastion_ip or not bastion_user or not bastion_pass:
                        st.error("⚠️ Please fill in all Bastion connection details before deploying.")
                    else:
                        st.session_state.bastion_ip = bastion_ip
                        st.session_state.bastion_port = bastion_port
                        st.session_state.bastion_user = bastion_user
                        st.session_state.bastion_pass = bastion_pass
                        
                        # Step 3: Check connectivity using extracted/custom Port
                        with st.spinner(f"Verifying SSH connectivity to {bastion_ip}:{bastion_port}..."):
                            is_reachable = check_ip_reachable(bastion_ip, port=bastion_port)
                        
                        if not is_reachable:
                            st.error(f"❌ Error: Host '{bastion_ip}' is unreachable on port {bastion_port}. Check network connectivity and firewall rules.")
                        else:
                            try:
                                playbook_path_server = os.path.join("bastion", "temp", "server-config.yaml")
                                playbook_path_bastion = os.path.join("bastion", "temp", "bastion-config.yaml")
                                
                                st.info(f"🚀 AI-Agent starting setup on Bastion ({bastion_ip}:{bastion_port}). Session logs below:")
                                
                                log_placeholder = st.empty()
                                accumulated_logs = ""
                                
                                # Environment setup for Ansible
                                env = os.environ.copy()
                                env["ANSIBLE_HOST_KEY_CHECKING"] = "False"

                                # Step 4: Determine playbooks to run based on Hardware Type
                                hardware_type = str(st.session_state.get("hardware_type", "")).strip().lower()

                                if hardware_type == "virtual":
                                    playbooks_to_run = [playbook_path_server, playbook_path_bastion]
                                else:
                                    playbooks_to_run = [playbook_path_bastion]

                                # Step 5: Execute Playbook(s) sequentially
                                all_passed = True
                                for playbook in playbooks_to_run:
                                    accumulated_logs += f"\n▶️ Running Playbook: {os.path.basename(playbook)}\n"
                                    accumulated_logs += "--------------------------------------------------\n"
                                    log_placeholder.code(accumulated_logs, language='text')

                                    ansible_cmd = [
                                        "ansible-playbook",
                                        "-i", f"{bastion_ip},",
                                        "-e", f"ansible_user={bastion_user}",
                                        "-e", f"ansible_password={bastion_pass}",
                                        "-e", f"ansible_port={bastion_port}",
                                        "-e", "ansible_ssh_common_args='-o StrictHostKeyChecking=no'",
                                        playbook
                                    ]

                                    process = subprocess.Popen(
                                        ansible_cmd, 
                                        stdout=subprocess.PIPE, 
                                        stderr=subprocess.STDOUT, 
                                        text=True, 
                                        bufsize=1,
                                        env=env
                                    )
                                    
                                    for line in process.stdout:
                                        accumulated_logs += line
                                        log_placeholder.code(accumulated_logs, language='text')
                                    
                                    process.wait()

                                    if process.returncode != 0:
                                        all_passed = False
                                        st.error(f"❌ Execution failed for playbook: {os.path.basename(playbook)}")
                                        break  # Stop further playbook execution if one fails
                                
                                if all_passed:
                                    st.success("🎉 Bastion Node configured successfully!")
                                else:
                                    st.error("❌ Ansible execution failed. Check the logs above for diagnostic details.")
                                        
                            except FileNotFoundError:
                                st.error("❌ Failed to run playbook. Ensure `ansible-playbook` and `sshpass` are installed on the local system.")
                            except Exception as e:
                                st.error(f"An unexpected error occurred during execution: {e}")
if __name__ == "__main__":
    main()