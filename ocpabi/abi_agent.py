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
        with open(filepath, 'r') as file:
            return file.read()
    return "Error: File not found."

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
        
        # Section 1
        section1_df = df.iloc[start_idx:split_idx]
        section1_df = section1_df.dropna(how='all')
        
        for index, row in section1_df.iterrows():
            key = row[0]
            value = row[1]
            if pd.notna(key) and key != 'Parameter Name':
                sheet_json_data[str(key).strip()] = str(value).strip() if pd.notna(value) else ""
        
        # Section 2
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
# 3. INSTALL-CONFIG GENERATOR
# ==========================================
def generate_install_config_yaml(json_input_file, yaml_output_file):
    if not os.path.exists(json_input_file):
        raise FileNotFoundError(f"Input file {json_input_file} not found.")

    with open(json_input_file, 'r') as f:
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

    env = Environment(loader=FileSystemLoader(get_bundled_path('ocpabi')))
    template = env.get_template("install-config.j2")
    rendered_yaml = template.render(OCP_Instalation_Input=config_vars)

    with open(yaml_output_file, 'w') as f:
        f.write(rendered_yaml)

# ==========================================
# 4. AGENT-CONFIG GENERATOR
# ==========================================
def generate_agent_config_yaml(json_input_file, yaml_output_file):
    if not os.path.exists(json_input_file):
        raise FileNotFoundError(f"Input file {json_input_file} not found.")

    with open(json_input_file, 'r') as f:
        data = json.load(f)
        
    config_vars = data.get("OCP_Instalation_Input", {})
    if not config_vars:
        raise ValueError("The key 'OCP_Instalation_Input' was not found in the JSON file.")

    hardware_type = config_vars.get("Hardware_Type", "").strip().lower()
    selected_template = "virtual-agent-config.j2" if hardware_type == "virtual" else "bm-agent-config.j2"

    env = Environment(
        loader=FileSystemLoader(get_bundled_path('ocpabi')), 
        trim_blocks=True, 
        lstrip_blocks=True
    )
    template = env.get_template(selected_template)
    rendered_yaml = template.render(data=config_vars)

    with open(yaml_output_file, 'w') as f:
        f.write(rendered_yaml)

# ==========================================
# 5. ANSIBLE-PLAYBOOK GENERATOR
# ==========================================
def generate_ansible_playbook_yaml(json_input_file, yaml_output_file):
    if not os.path.exists(json_input_file):
        raise FileNotFoundError(f"Input file {json_input_file} not found.")

    with open(json_input_file, 'r') as f:
        data = json.load(f)
        
    config_vars = data.get("OCP_Instalation_Input", {})
    if not config_vars:
        raise ValueError("The key 'OCP_Instalation_Input' was not found in the JSON file.")

    env = Environment(loader=FileSystemLoader(get_bundled_path('ocpabi')), trim_blocks=True, lstrip_blocks=True)
    template = env.get_template("ansible-playbook.j2")
    rendered_yaml = template.render(OCP_Instalation_Input=config_vars)

    with open(yaml_output_file, 'w') as f:
        f.write(rendered_yaml)

# ==========================================
# 6. STREAMLIT UI MAIN APP
# ==========================================
def main():
    if 'pipeline_completed' not in st.session_state:
        st.session_state.pipeline_completed = False
    if 'playbook_generated' not in st.session_state:
        st.session_state.playbook_generated = False
    if 'hardware_type' not in st.session_state:
        st.session_state.hardware_type = "Virtual"
    if 'show_ai_deploy' not in st.session_state:
        st.session_state.show_ai_deploy = False

    st.set_page_config(page_title="OpenShift Orchestrator", layout="centered")

    st.title("🚀 ABI method OpenShift Deployment Orchestrator")
    st.markdown("""
    ### How this tool Work:
    1. **Browse and Upload:** Select your OpenShift Configuration Excel file name. Make sure sheet name and variable name should be same as sample file.
    2. **Execute Pipeline:** Generate the installation configurations.
    3. **Deploy:** Follow the manual instructions, or provide Bastion credentials to push the configs via Ansible.
    ---
    """)

    uploaded_file = st.file_uploader("**Select the OpenShift Configuration Excel File (.xlsx)**", type=["xlsx", "xls"])

    if uploaded_file is not None:
        if st.button(f"▶️ Your File **{uploaded_file.name}** is ready for process and Required your approval", type="primary"):
            try:
                # Directory Setup
                target_folder = os.path.join(os.getcwd(), "ocpabi", "temp")
                os.makedirs(target_folder, exist_ok=True)
                
                excel_path = os.path.join(target_folder, "abi-ocp-input.xlsx")
                json_path = os.path.join(target_folder, "abi-ocp-input.json")
                install_config_path = os.path.join(target_folder, "install-config.yaml")
                agent_config_path = os.path.join(target_folder, "agent-config.yaml")
                ansible_playbook_path = os.path.join(target_folder, "deploy-ocp.yaml")               
                
                # Step 1: Save Uploaded File
                with st.spinner("Saving Excel file locally..."):
                    with open(excel_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                
                # Step 2: Convert Excel to JSON
                with st.spinner("Executing Agent to generate input file..."):
                    convert_custom_excel_to_json(excel_path, json_path)

                # Step 3: Generate install-config.yaml
                with st.spinner("Executing agent-install-config ..."):
                    generate_install_config_yaml(json_path, install_config_path)

                # Step 4: Generate agent-config.yaml
                with st.spinner("Executing agent-agent-config ..."):
                    generate_agent_config_yaml(json_path, agent_config_path)

                # Step 5: Generate ansible-playbook.yaml
                with st.spinner("Executing agent-ansible-playbook ..."):
                    generate_ansible_playbook_yaml(json_path, ansible_playbook_path)

                # Extract Hardware Type for future steps
                with open(json_path, "r") as json_file:
                    ocp_data = json.load(json_file)
                    st.session_state.hardware_type = str(ocp_data.get("OCP_Instalation_Input", {}).get("Hardware_Type", "Virtual")).strip()

                st.session_state.pipeline_completed = True
                st.session_state.show_ai_deploy = False 
                st.session_state.playbook_generated = False
                
                st.success("🎉 AI-ChatBot Successfully Generated your configuration file and ready for The review.")
                
            except Exception as e:
                st.error(f"❌ An error occurred during the pipeline execution:\n\n{e}")

    # --- UI STEP 2: Review Files ---
    if st.session_state.pipeline_completed:
        with st.expander("👀 Review your install-config.yaml file"):
            st.code(read_file("ocpabi/temp/install-config.yaml"), language='yaml')

        with st.expander("👀 Review your agent-config.yaml file"):
            st.code(read_file("ocpabi/temp/agent-config.yaml"), language='yaml')

        st.markdown("### 🛠️ Manual ABI Method Deployment Instructions")
        st.markdown("""
        **To deploy OpenShift manually using the Agent-Based Installer (ABI), follow these steps:**
        1. Create a working directory on your build machine (e.g., `mkdir cluster-config`).
        2. Move the generated `install-config.yaml` and `agent-config.yaml` into that directory.
        3. Generate the bootable ISO by running: 
           ```bash
           openshift-install agent create image --dir=cluster-config
           ```
        4. Mount `agent.x86_64.iso` file to all server and boot all server same time. Once you start the Server OCP installation start autometically
        5. Monitor the installation progress by running:
           ```bash
           openshift-install --dir=cluster-config wait-for install-complete
           ```
        """)
        
        # --- UI STEP 3 & 4: Automated Background Deployment ---
        if st.button("🤖 Would you prefer the AI-Agent to configure the Bastion Node automatically?", type="primary"):
            st.session_state.show_ai_deploy = True
            
        if st.session_state.show_ai_deploy:
            st.markdown("#### 🖥️ Review the Bastion Detail")
            
            json_input_path = os.path.join("ocpabi", "temp", "abi-ocp-input.json")
            
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
                
                deploy_btn = st.form_submit_button("🔥 Deploy the OCP Cluster", type="primary")
                
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
                                playbook_path = os.path.join("ocpabi", "temp", "deploy-ocp.yaml")
                                
                                st.info(f"🚀 TASK 1: AI-Agent starting setup on Bastion ({bastion_ip}:{bastion_port}). Session logs below:")
                                
                                log_placeholder = st.empty()
                                accumulated_logs = ""
                                
                                # Step 4: Execute Playbook from Local AI Host against Target Bastion
                                env = os.environ.copy()
                                env["ANSIBLE_HOST_KEY_CHECKING"] = "False"
                                
                                ansible_cmd = [
                                    "ansible-playbook",
                                    "-i", f"{bastion_ip},",
                                    "-e", f"ansible_user={bastion_user}",
                                    "-e", f"ansible_password={bastion_pass}",
                                    "-e", f"ansible_port={bastion_port}",
                                    "-e", "ansible_ssh_common_args='-o StrictHostKeyChecking=no'",
                                    playbook_path
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
                                
                                if process.returncode == 0:
                                    # ==========================================
                                    # TASK 2: CHECK DEPLOYMENT PROCESS & SHOW LOGS
                                    # ==========================================
                                    st.info("🔍 TASK 2: Checking deployment process and streaming status logs from Bastion...")
                                    
                                    accumulated_logs += "\n" + "=" * 65 + "\n"
                                    accumulated_logs += "Starting TASK 2: Checking Deployment Progress & Status Logs...\n"
                                    accumulated_logs += "=" * 65 + "\n\n"
                                    log_placeholder.code(accumulated_logs, language='text')
                                    
                                    # Command to check process/log file on bastion.
                                    # Adjust the target log path or status command as needed for your setup:
                                    check_cmd_str = (
                                        "sleep 60"
                                        "openshift-install agent wait-for bootstrap-complete --log-level=debug --dir=/root/abi/"
                                        "echo 'node ready for the Deployment"
                                        "openshift-install agent wait-for install-complete --log-level=debug --dir=/root/abi/"
                                        "deployment done"
                                    )
                                    
                                    check_cmd = [
                                        "sshpass", "-p", bastion_pass,
                                        "ssh",
                                        "-p", str(bastion_port),
                                        "-o", "StrictHostKeyChecking=no",
                                        f"{bastion_user}@{bastion_ip}",
                                        check_cmd_str
                                    ]
                                    
                                    check_process = subprocess.Popen(
                                        check_cmd,
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT,
                                        text=True,
                                        bufsize=1
                                    )
                                    
                                    for line in check_process.stdout:
                                        accumulated_logs += line
                                        log_placeholder.code(accumulated_logs, language='text')
                                        
                                    check_process.wait()
                                    
                                    if check_process.returncode == 0:
                                        st.success("🎉 All deployment tasks and status checks have been completed successfully!")
                                    else:
                                        st.warning("⚠️ Task 1 finished, but checking deployment logs encountered an issue.")
                                else:
                                    st.error("❌ Deployment failed: Ansible playbook run encountered an error. Please check the logs above for details.")
                                        
                            except FileNotFoundError:
                                st.error("❌ Failed to run command. Ensure both `ansible-playbook` and `sshpass` are installed on the system running Streamlit.")
                            except Exception as e:
                                st.error(f"An error occurred during execution: {e}")

if __name__ == "__main__":
    main()