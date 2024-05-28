import time
import streamlit as st
from shared.constants import QUEUE_INFERENCE_QUERIES, InferenceType
from ui_components.methods.common_methods import process_inference_output
from ui_components.widgets.sidebar_logger import sidebar_logger
from ui_components.widgets.cropping_element import cropping_selector_element
from ui_components.widgets.frame_selector import frame_selector_widget, frame_view
from ui_components.widgets.add_key_frame_element import add_key_frame, add_key_frame_element
from ui_components.widgets.timeline_view import timeline_view
from ui_components.components.explorer_page import generate_images_element
from ui_components.widgets.inpainting_element import inpainting_element, inpainting_image_input
from ui_components.widgets.drawing_element import drawing_element
from ui_components.widgets.variant_comparison_grid import variant_comparison_grid
from utils import st_memory

from ui_components.constants import CreativeProcessType
from utils.constants import MLQueryObject
from utils.data_repo.data_repo import DataRepo
from utils.ml_processor.constants import ML_MODEL
from utils.ml_processor.ml_interface import get_ml_client


def frame_styling_page(shot_uuid: str):
    data_repo = DataRepo()
    shot = data_repo.get_shot_from_uuid(shot_uuid)
    timing_list = data_repo.get_timing_list_from_shot(shot_uuid)

    if len(timing_list) == 0:
        st.markdown("#### There are no frames present in this shot yet.")

    else:
        with st.sidebar:
            """st.session_state['styling_view'] = st_memory.menu('',\
                                    ["Crop","Inpaint"], \
                                        icons=['magic', 'crop', "paint-bucket", 'pencil'], \
                                            menu_icon="cast", default_index=st.session_state.get('styling_view_index', 0), \
                                                key="styling_view_selector", orientation="horizontal", \
                                                    styles={"nav-link": {"font-size": "15px", "margin": "0px", "--hover-color": "#3f6e99"}, "nav-link-selected": {"background-color": "#60b4ff"}})
            """
            st.write("")
            with st.expander("🔍 Generation log", expanded=True):
                # if st_memory.toggle("Open", value=True, key="generaton_log_toggle"):
                sidebar_logger(st.session_state["shot_uuid"])

            frame_view(view="Key Frame")

        st.markdown(
            f"#### :green[{st.session_state['main_view_type']}] > :red[Adjust Shot] > :blue[{shot.name} - #{st.session_state['current_frame_index']}]"
        )
        variant_comparison_grid(
            st.session_state["current_frame_uuid"], stage=CreativeProcessType.STYLING.value
        )

        # with st.expander("🛠️ Generate Variants", expanded=True):
        #    generate_images_element(position='individual', project_uuid=shot.project.uuid, timing_uuid=st.session_state['current_frame_uuid'])

        st.markdown("***")

        with st.expander("🤏 Crop, Move & Rotate", expanded=True):
            cropping_selector_element(shot_uuid)

        st.markdown("***")

        with st.expander("🌌 Inpainting", expanded=True):

            options_width, canvas_width = st.columns([1.2, 3])
            timing_uuid = st.session_state["current_frame_uuid"]
            timing = data_repo.get_timing_from_uuid(timing_uuid)
            with options_width:
                prompt = st_memory.text_area(
                    "Prompt:",
                    key=f"base_prompt_{timing_uuid}",
                    help="Describe what's in the area you want to inpaint",
                )

                negative_prompt = st_memory.text_area(
                    "Negative prompt:",
                    value="",
                    key=f"neg_base_prompt_{timing_uuid}",
                    help="These are the things you wish to be excluded from the image",
                )
            with canvas_width:
                inpainting_element(options_width, timing.primary_image.location, position=f"{timing_uuid}")

            with options_width:
                if "mask_to_use" not in st.session_state:
                    st.session_state["mask_to_use"] = ""
                if st.session_state["mask_to_use"] != "":
                    how_many_images = st.slider(
                        "How many images to generate:", 1, 10, 1, key=f"how_many_images_{timing_uuid}"
                    )
                    if st.button("Generate inpainted images", key=f"generate_inpaint_{timing_uuid}"):
                        if "mask_to_use" in st.session_state and st.session_state["mask_to_use"]:
                            for _ in range(how_many_images):  # Loop based on how_many_images
                                project_settings = data_repo.get_project_setting(shot.project.uuid)
                                query_obj = MLQueryObject(
                                    timing_uuid=None,
                                    model_uuid=None,
                                    guidance_scale=8,
                                    seed=-1,
                                    num_inference_steps=25,
                                    strength=0.5,
                                    adapter_type=None,
                                    prompt=prompt,
                                    negative_prompt=negative_prompt,
                                    height=project_settings.height,
                                    width=project_settings.width,
                                    data={
                                        "shot_uuid": shot_uuid,
                                        "mask": st.session_state["mask_to_use"],
                                        "input_image": st.session_state["editing_image"],
                                        "project_uuid": shot.project.uuid,
                                    },
                                )

                                ml_client = get_ml_client()
                                output, log = ml_client.predict_model_output_standardized(
                                    ML_MODEL.sdxl_inpainting,
                                    query_obj,
                                    queue_inference=QUEUE_INFERENCE_QUERIES,
                                )

                                if log:
                                    inference_data = {
                                        "inference_type": InferenceType.FRAME_TIMING_IMAGE_INFERENCE.value,
                                        "output": output,
                                        "log_uuid": log.uuid,
                                        "project_uuid": shot.project.uuid,
                                        "timing_uuid": timing_uuid,
                                        "promote_new_generation": False,
                                        "shot_uuid": shot_uuid if shot_uuid else "explorer",
                                    }

                                    process_inference_output(**inference_data)
                            st.rerun()
                else:
                    st.error("You must first select the area to inpaint.")

        # elif st.session_state['styling_view'] == "Scribble":
        # with st.expander("📝 Draw On Image", expanded=True):
        #  drawing_element(shot_uuid)

        st.markdown("***")
